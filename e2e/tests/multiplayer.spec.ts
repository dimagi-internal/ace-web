import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";
import { addParticipant, createSession, listMessages } from "../helpers/session";

/**
 * Phase 3 multi-player E2E smoke test.
 *
 * Exercises the reviewer's manual checklist as automated
 * assertions against the full stack (React + Channels + FakeCLIBackend):
 *  1. Alice connects, sees session.state (SendBox textarea becomes
 *     the "Type a message" variant).
 *  2. Bob logs in up-front so Alice can add him as a participant
 *     (the participant-add endpoint 404s if the user has never
 *     logged in, so Bob's loginAs() has to happen first).
 *  3. Bob connects to the same session URL in a separate browser
 *     context and receives his own session.state.
 *  4. Alice types → Bob sees the draft body live via draft.updated
 *     broadcasts. Bob's textarea locks while Alice holds.
 *  5. Draft idle transition at T+2s unlocks Bob's textarea.
 *  6. Alice sends → the server commits the draft, runs the
 *     FakeCLIBackend turn, and both Alice and Bob see the user
 *     bubble and the streaming assistant bubble in the DOM.
 *  7. Bob clicks the stop button on Alice's in-flight turn, and the
 *     server flips the assistant message to ``status: "error"``
 *     with a cancelled detail. See the second test below.
 *
 * The server runs under ``config/settings/e2e.py``, which uses
 * ``InMemoryChannelLayer`` + sqlite + ``ACE_ALLOW_TEST_LOGIN`` +
 * ``ACE_USE_FAKE_CLI_BACKEND``, and ``config/asgi_e2e.py``, which
 * strips the ``/ace/`` prefix from websocket scope paths and
 * patches ``redis_client.get_redis`` to return a fakeredis
 * instance. No Redis, no Postgres, no Docker.
 */
test.describe("Phase 3 multi-player", () => {
  test("Alice and Bob collaborate on a session", async ({ browser }) => {
    // 1. Alice logs in (test-login creates the User on first hit).
    const alice = await newAuthedContext(browser, "alice@dimagi.com", "Alice");

    // 2. Bob also has to log in up-front so the participant-add
    //    endpoint can find him by email.
    const bob = await newAuthedContext(browser, "bob@dimagi.com", "Bob");

    // Alice creates a session and adds Bob.
    const slug = await createSession(alice.page, "Multiplayer test");
    await addParticipant(alice.page, slug, "bob@dimagi.com");

    // Alice navigates to the chat page.
    await alice.page.goto(`/ace/chat/${slug}`);
    await expect(alice.page).toHaveURL(new RegExp(`/ace/chat/${slug}`));

    // Wait for the WebSocket to connect and session.state to
    // populate. The SendBox placeholder flips from "Connecting…" to
    // "Type a message…" once the active_draft arrives and Alice is
    // recognised as the holder.
    const aliceTextarea = alice.page.getByRole("textbox");
    await expect(aliceTextarea).toBeVisible({ timeout: 10_000 });
    await expect(aliceTextarea).toHaveAttribute(
      "placeholder",
      /Type a message/,
      { timeout: 10_000 },
    );

    // 3. Bob opens the same session URL.
    await bob.page.goto(`/ace/chat/${slug}`);
    const bobTextarea = bob.page.getByRole("textbox");
    await expect(bobTextarea).toBeVisible({ timeout: 10_000 });

    // 4. Alice types → Bob sees the draft body live.
    await aliceTextarea.fill("Hello from Alice");
    // The hook debounces 150ms before sending; give the server
    // round-trip a beat plus a generous margin.
    await expect(bobTextarea).toHaveValue("Hello from Alice", {
      timeout: 5_000,
    });

    // Bob's textarea should be in the locked state (Alice is the
    // holder and the draft is not yet idle).
    await expect(bobTextarea).toBeDisabled();

    // 5. Draft idle transition at T+2s unlocks Bob.
    //    The SendBox schedules a forceTick setTimeout at
    //    lastEdit + 2s. Wait a bit past the 2s threshold to avoid
    //    flake.
    await alice.page.waitForTimeout(2_500);
    await expect(bobTextarea).toBeEnabled({ timeout: 2_000 });

    // 6. Alice sends → server-side the draft is committed, the
    //    assistant turn runs, and the FakeCLIBackend yields
    //    "Echo: Hello from Alice" as deltas over ~1.5s.
    //
    // Click the send button rather than pressing Enter on the
    // textarea: Playwright's keyboard events on a React-controlled
    // textarea can race with the React onKeyDown handler if the
    // component re-renders between focus and keypress, and a
    // button click is the most direct path to ``onSend()``.
    const aliceSendButton = alice.page.getByRole("button", { name: /^send$/ });
    await expect(aliceSendButton).toBeEnabled({ timeout: 5_000 });
    await aliceSendButton.click();

    // Wait for the server-side draft body to clear, which is the
    // observable signal that chat.send was accepted.
    await expect(aliceTextarea).toHaveValue("", { timeout: 5_000 });

    // Alice's user message bubble should appear in the DOM. The
    // useSessionSocket draft.committed reducer inserts the user
    // message (constructed from the about-to-be-cleared draft body)
    // plus an assistant placeholder into React state, so both are
    // visible without a page reload.
    await expect(
      alice.page.getByText("Hello from Alice", { exact: true }),
    ).toBeVisible();
    await expect(
      alice.page.getByText(/Echo: Hello from Alice/),
    ).toBeVisible({ timeout: 10_000 });

    // Bob sees the same bubbles on his separate page/context.
    await expect(
      bob.page.getByText("Hello from Alice", { exact: true }),
    ).toBeVisible();
    await expect(
      bob.page.getByText(/Echo: Hello from Alice/),
    ).toBeVisible({ timeout: 10_000 });

    // The streaming cursor (the pulsing caret rendered inside a
    // streaming assistant bubble) should disappear once
    // chat.stream_complete arrives and the reducer flips the
    // message to status="complete". See
    // frontend/src/components/MessageItem.tsx for the element.
    await expect(alice.page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 10_000,
    });
    await expect(bob.page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 10_000,
    });

    // Secondary wire-contract check: the persisted rows should
    // match what the UI shows. Now that the turn_driver
    // _mark_complete fix is in, the assistant row should also be
    // status="complete" (previously stuck at "streaming").
    const finalMessages = await listMessages(alice.page, slug);
    const userMsg = finalMessages.find((m) => m.role === "user");
    const assistantMsg = finalMessages.find((m) => m.role === "assistant");
    expect(userMsg?.plaintext).toBe("Hello from Alice");
    expect(userMsg?.status).toBe("complete");
    expect(assistantMsg?.status).toBe("complete");
    expect(assistantMsg?.plaintext).toBe("Echo: Hello from Alice");

    // Clean up.
    await alice.context.close();
    await bob.context.close();
  });

  test("Bob stops Alice's in-flight stream", async ({ browser }) => {
    const alice = await newAuthedContext(browser, "alice@dimagi.com", "Alice");
    const bob = await newAuthedContext(browser, "bob@dimagi.com", "Bob");

    const slug = await createSession(alice.page, "Stop test");
    await addParticipant(alice.page, slug, "bob@dimagi.com");

    await alice.page.goto(`/ace/chat/${slug}`);
    await bob.page.goto(`/ace/chat/${slug}`);

    const aliceTextarea = alice.page.getByRole("textbox");
    await expect(aliceTextarea).toBeVisible({ timeout: 10_000 });
    await expect(aliceTextarea).toHaveAttribute(
      "placeholder",
      /Type a message/,
      { timeout: 10_000 },
    );
    const bobTextarea = bob.page.getByRole("textbox");
    await expect(bobTextarea).toBeVisible({ timeout: 10_000 });

    // Alice sends a prompt. The FakeCLIBackend yields deltas of
    // chunk_size=4 chars every 100ms, so a ~60-char prompt gives a
    // ~1.5s streaming window — plenty of time for Bob to click
    // stop before the turn completes.
    const prompt = "a moderately long prompt for stop testing end-to-end flow";
    await aliceTextarea.fill(prompt);
    await expect(bobTextarea).toHaveValue(prompt, { timeout: 5_000 });
    const aliceSendButton = alice.page.getByRole("button", { name: /^send$/ });
    await expect(aliceSendButton).toBeEnabled({ timeout: 5_000 });
    await aliceSendButton.click();

    // Now that the draft.committed reducer inserts the assistant
    // placeholder into React state, the ChatPage streamingMessage
    // memo resolves to the new row and SendBox renders its stop
    // button. Wait for Bob's stop button to become visible — this
    // is the cross-consumer "any participant can cancel" affordance.
    const bobStopButton = bob.page.getByRole("button", { name: /^stop$/ });
    await expect(bobStopButton).toBeVisible({ timeout: 5_000 });
    await bobStopButton.click();

    // After Bob's click the server cancels the in-flight turn.
    // Observable signals on both pages:
    //   - The stop button disappears on Bob's page (isStreaming
    //     flips to false once the assistant message is no longer
    //     status="streaming").
    //   - The streaming cursor disappears on Alice's page for
    //     the same reason.
    await expect(bobStopButton).not.toBeVisible({ timeout: 5_000 });
    await expect(alice.page.locator(".animate-pulse")).not.toBeVisible({
      timeout: 5_000,
    });

    // Secondary wire-contract check: the server-side row should
    // be flipped to error with the "cancelled" detail. This
    // catches server-side regressions even if the UI somehow
    // mislabels the state.
    await expect
      .poll(async () => {
        const messages = await listMessages(alice.page, slug);
        const assistant = messages.find((m) => m.role === "assistant");
        return assistant?.status ?? null;
      }, { timeout: 10_000 })
      .toBe("error");
    const finalMessages = await listMessages(alice.page, slug);
    const assistant = finalMessages.find((m) => m.role === "assistant");
    expect(assistant?.error_detail ?? "").toMatch(/cancel/i);

    await alice.context.close();
    await bob.context.close();
  });

  test("Alice disconnecting removes her from Bob's presence chips", async ({
    browser,
  }) => {
    const alice = await newAuthedContext(browser, "alice@dimagi.com", "Alice");
    const bob = await newAuthedContext(browser, "bob@dimagi.com", "Bob");

    const slug = await createSession(alice.page, "Presence test");
    await addParticipant(alice.page, slug, "bob@dimagi.com");

    await alice.page.goto(`/ace/chat/${slug}`);
    await bob.page.goto(`/ace/chat/${slug}`);

    // Wait for both sockets to connect + session.state to arrive.
    // PresenceChips renders a <div title="Alice...">..." /> and a
    // <div title="Bob..."> for each present participant (see
    // frontend/src/components/PresenceChips.tsx).
    await expect(alice.page.getByRole("textbox")).toBeVisible({
      timeout: 10_000,
    });
    await expect(bob.page.getByRole("textbox")).toBeVisible({
      timeout: 10_000,
    });

    // Bob should see both chips after Alice joins.
    await expect(bob.page.getByTitle(/Alice/)).toBeVisible({ timeout: 5_000 });
    await expect(bob.page.getByTitle(/Bob/)).toBeVisible();

    // Alice closes her context — this cleanly closes the WebSocket,
    // which triggers the consumer's disconnect() handler, which
    // broadcasts presence.left to the session group.
    await alice.context.close();

    // Bob's presence.left handler removes Alice's user id from
    // presence_user_ids, and PresenceChips filters participants by
    // that list, so Alice's chip disappears.
    await expect(bob.page.getByTitle(/Alice/)).not.toBeVisible({
      timeout: 5_000,
    });
    // Bob's own chip stays — he's still present.
    await expect(bob.page.getByTitle(/Bob/)).toBeVisible();

    await bob.context.close();
  });

  test("Bob can reconnect after his WebSocket drops", async ({ browser }) => {
    const alice = await newAuthedContext(browser, "alice@dimagi.com", "Alice");
    const bob = await newAuthedContext(browser, "bob@dimagi.com", "Bob");

    const slug = await createSession(alice.page, "Reconnect test");
    await addParticipant(alice.page, slug, "bob@dimagi.com");

    await alice.page.goto(`/ace/chat/${slug}`);
    await bob.page.goto(`/ace/chat/${slug}`);

    const aliceTextarea = alice.page.getByRole("textbox");
    const bobTextarea = bob.page.getByRole("textbox");
    await expect(aliceTextarea).toBeVisible({ timeout: 10_000 });
    await expect(bobTextarea).toBeVisible({ timeout: 10_000 });

    // Sanity check baseline propagation is working before we
    // disrupt Bob's socket.
    await aliceTextarea.fill("before-drop");
    await expect(bobTextarea).toHaveValue("before-drop", { timeout: 5_000 });

    // Navigate Bob away (closing his page's WebSocket via
    // useSessionSocket's useEffect cleanup), then back. This is a
    // coarse stand-in for a socket drop: it exercises the
    // end-to-end "my chat keeps working after a disruption" flow
    // from the user's perspective without requiring init-script
    // monkey-patching of window.WebSocket. A fresh hook instance
    // mounts, opens a new socket, and receives the server's
    // current session.state snapshot.
    await bob.page.goto("about:blank");
    await bob.page.waitForTimeout(500);
    await bob.page.goto(`/ace/chat/${slug}`);

    // After reconnect, Bob's textarea should show the current
    // draft body. The session.state reducer replaces the whole
    // state with the server's snapshot on reconnect.
    const bobTextareaAfter = bob.page.getByRole("textbox");
    await expect(bobTextareaAfter).toBeVisible({ timeout: 10_000 });
    await expect(bobTextareaAfter).toHaveValue("before-drop", {
      timeout: 5_000,
    });

    // Verify Alice's subsequent edit still reaches Bob through
    // the new socket.
    await aliceTextarea.fill("after-reconnect");
    await expect(bobTextareaAfter).toHaveValue("after-reconnect", {
      timeout: 5_000,
    });

    await alice.context.close();
    await bob.context.close();
  });

  test("Adding a non-existent teammate shows an error", async ({ browser }) => {
    const alice = await newAuthedContext(browser, "alice@dimagi.com", "Alice");

    const slug = await createSession(alice.page, "Add-teammate error test");

    await alice.page.goto(`/ace/chat/${slug}`);
    await expect(alice.page.getByRole("textbox")).toBeVisible({
      timeout: 10_000,
    });

    // Click the "+ teammate" button to open the inline form.
    await alice.page
      .getByRole("button", { name: /\+ teammate/ })
      .click();

    // The email input appears inline.
    const emailInput = alice.page.getByPlaceholder(/name@dimagi\.com/);
    await expect(emailInput).toBeVisible({ timeout: 3_000 });

    // Enter an email that doesn't correspond to any logged-in
    // user. The server returns 404 with {error: {code:
    // "not_found", message: "no user with that email has logged
    // in yet"}}.
    await emailInput.fill("ghost@dimagi.com");
    await alice.page.getByRole("button", { name: /^add$/ }).click();

    // AddTeammateButton surfaces the error via a red span; see
    // frontend/src/components/AddTeammateButton.tsx. The envelope's
    // error.message becomes e.message in the catch block.
    await expect(
      alice.page.getByText(/no user with that email has logged in yet/),
    ).toBeVisible({ timeout: 5_000 });

    await alice.context.close();
  });
});
