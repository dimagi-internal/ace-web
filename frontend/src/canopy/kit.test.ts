import { ChatPanel, useSessionSocket, PlacementBanner } from "canopy-ui/chat"
import { expect, test } from "vitest"

test("kit exports resolve", () => {
  expect(ChatPanel).toBeTruthy()
  expect(useSessionSocket).toBeTruthy()
  expect(PlacementBanner).toBeTruthy()
})
