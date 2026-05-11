// Smoke test — proves the vitest harness is wired up.
// Drop me when there are real tests.
import { describe, expect, it } from "vitest"

describe("test harness", () => {
  it("runs", () => {
    expect(1 + 1).toBe(2)
  })
})
