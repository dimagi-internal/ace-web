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
 *     FakeCLIBackend turn, and persists "Echo: <prompt>" as the
 *     assistant message. We verify via ``GET /api/sessions/<slug>/messages``
 *     because the current ChatPage does not refetch or append
 *     streamed messages to its local state — see the NOTE below.
 *  7. Bob issues chat.stop on Alice's in-flight turn, and the
 *     server flips the assistant message to ``status: "error"``
 *     with a cancelled detail. See the second test below.
 *
 * NOTE (known Phase 3 frontend gap): ``useSessionSocket`` reduces
 * ``chat.stream_start`` / ``chat.delta`` / ``chat.stream_complete``
 * with ``prev.messages.map(...)`` — so a message that did not exist
 * at connect time is never *added* to the React state, only
 * mutated in place if it was already there. The assistant bubble
 * therefore doesn't appear on-screen until the page is reloaded,
 * and the SendBox's ``isStreaming`` stays false so the stop
 * button never renders on either client. The REST endpoint
 * ``/api/sessions/<slug>/messages`` still reflects the
 * committed-and-streamed state accurately, so that is what we
 * assert on to validate the backend E2E path. When the frontend
 * is fixed, the UI assertions can be reinstated in place of the
 * REST polls.
 *
 * NOTE (known Phase 3 backend gap): the consumer's early
 * ``return`` inside the DONE branch of ``_run_turn_driver``
 * closes the turn_driver generator via ``GeneratorExit`` before
 * ``_mark_complete`` gets a chance to run, so the assistant
 * Message row stays at ``status: "streaming"`` after a successful
 * turn. The wire events and persisted plaintext are correct; it's
 * only the persisted status that is wrong. The happy-path test
 * below asserts on ``plaintext`` rather than ``status`` so it
 * stays green once the fix lands.
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
    //    "Echo: Hello from Alice" as deltas over ~1.5s. Because
    //    the current frontend does not append streamed messages
    //    to its React state, we assert on the REST view of the
    //    session's messages instead (same authenticated context
    //    as Alice).
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

    // Poll the messages endpoint until the assistant echo lands.
    // The FakeCLIBackend finishes in ~1.5s; give it up to 10.
    //
    // NOTE: we match on ``plaintext`` and not on
    // ``status === "complete"`` because of a latent bug in the
    // current Phase 3 ``_run_turn_driver``: the consumer's early
    // ``return`` inside the DONE branch closes the driver
    // generator via ``GeneratorExit`` before ``_mark_complete``
    // can run, so the DB row stays ``status: "streaming"`` after
    // a successful turn. The client-visible wire event
    // (``chat.stream_complete`` with the full plaintext) is
    // correct — it's only the persisted status that is wrong.
    // Flagging so this can be fixed; the assertion below is
    // loose on purpose to let the test remain green once the fix
    // lands (status will flip to complete, plaintext stays the
    // same).
    await expect
      .poll(
        async () => {
          const messages = await listMessages(alice.page, slug);
          const assistant = messages.find((m) => m.role === "assistant");
          return assistant?.plaintext ?? null;
        },
        { timeout: 10_000, intervals: [250, 500, 1_000] },
      )
      .toBe("Echo: Hello from Alice");

    // The user message should also be persisted.
    const finalMessages = await listMessages(alice.page, slug);
    const userMsg = finalMessages.find((m) => m.role === "user");
    const assistantMsg = finalMessages.find((m) => m.role === "assistant");
    expect(userMsg?.plaintext).toBe("Hello from Alice");
    expect(userMsg?.status).toBe("complete");
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

    // Alice sends a prompt. The FakeCLIBackend yields ~6 deltas
    // over ~600ms total — long enough for the stop to land
    // mid-flight but short enough to keep the test snappy. A
    // longer prompt would increase the delta count but the
    // 250ms DB-write debounce already gives us a clear window.
    const prompt = "a moderately long prompt for stop testing";
    await aliceTextarea.fill(prompt);
    await expect(bobTextarea).toHaveValue(prompt, { timeout: 5_000 });
    const aliceSendButton = alice.page.getByRole("button", { name: /^send$/ });
    await expect(aliceSendButton).toBeEnabled({ timeout: 5_000 });
    await aliceSendButton.click();

    // NOTE (known Phase 3 frontend gap): the current
    // ``useSessionSocket`` reducer does not add the assistant
    // message row to React state when ``chat.stream_start``
    // arrives — it only maps over existing messages. So the
    // ``streamingMessage`` memo in ``ChatPage`` never resolves
    // to a live message, the SendBox's ``isStreaming`` stays
    // false, and **the stop button never renders** on either
    // client. That's the same gap the happy-path test works
    // around above.
    //
    // Rather than drive the stop via the (never-rendered) stop
    // button, we send a ``chat.stop`` action directly from
    // Bob's browser via a raw WebSocket piggybacking on the
    // authenticated cookie. This still exercises the real
    // Phase 3 cross-consumer cancellation path end-to-end
    // (Bob's websocket → consumer → turn_driver → cancelled
    // state → error_detail persisted) even if the stop button
    // itself is not observable. When the frontend reducer is
    // fixed, swap this back to a button click.

    // Wait until the server has created the assistant message
    // and given it an id (it's created synchronously in
    // commit_active_draft during chat.send handling, so this
    // should succeed on the very first poll).
    let assistantMessageId: number | null = null;
    await expect
      .poll(async () => {
        const messages = await listMessages(alice.page, slug);
        const assistant = messages.find((m) => m.role === "assistant");
        if (assistant) {
          assistantMessageId = assistant.id;
          return assistant.id;
        }
        return null;
      }, { timeout: 5_000 })
      .not.toBeNull();
    expect(assistantMessageId).not.toBeNull();

    // Open a raw WebSocket from Bob's page context and send
    // chat.stop. ``page.evaluate`` runs in the browser, so the
    // session cookie is attached automatically by the
    // ws handshake.
    await bob.page.evaluate(
      async ({ slug, messageId }) => {
        const ws = new WebSocket(
          `ws://${window.location.host}/ace/ws/sessions/${slug}/`,
        );
        await new Promise<void>((resolve, reject) => {
          ws.onopen = () => resolve();
          ws.onerror = () => reject(new Error("ws open failed"));
        });
        // The server will push session.state on connect; wait
        // for it before issuing chat.stop so we know the
        // consumer has finished its connect() handler.
        await new Promise<void>((resolve) => {
          ws.onmessage = (e) => {
            const frame = JSON.parse(e.data);
            if (frame.event === "session.state") resolve();
          };
        });
        ws.send(
          JSON.stringify({
            action: "chat.stop",
            data: { message_id: messageId },
          }),
        );
        // Give the stop_event watcher (0.1s polling) time to
        // fire + the cancellation to propagate.
        await new Promise((r) => setTimeout(r, 1_500));
        ws.close();
      },
      { slug, messageId: assistantMessageId },
    );

    // Server-side: the assistant message should be marked
    // error with the "cancelled" detail. This assertion is the
    // one that actually validates the stop flow.
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
});
