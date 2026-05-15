import "@testing-library/jest-dom/vitest"

// jsdom does not implement PointerEvent. RTL's fireEvent.pointerXxx
// dispatches an Event that drops clientX/clientY without a proper backing
// constructor — so widgets that rely on pointer coordinates (e.g. TrimBar)
// can't be tested. Polyfill PointerEvent as a MouseEvent subclass; this is
// the standard workaround used across the React testing ecosystem.
if (typeof window !== "undefined" && !("PointerEvent" in window)) {
  class PointerEventPolyfill extends MouseEvent {
    public pointerId: number
    public width: number
    public height: number
    public pressure: number
    public tangentialPressure: number
    public tiltX: number
    public tiltY: number
    public twist: number
    public pointerType: string
    public isPrimary: boolean

    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params)
      this.pointerId = params.pointerId ?? 0
      this.width = params.width ?? 1
      this.height = params.height ?? 1
      this.pressure = params.pressure ?? 0
      this.tangentialPressure = params.tangentialPressure ?? 0
      this.tiltX = params.tiltX ?? 0
      this.tiltY = params.tiltY ?? 0
      this.twist = params.twist ?? 0
      this.pointerType = params.pointerType ?? ""
      this.isPrimary = params.isPrimary ?? false
    }
  }
  // @ts-expect-error attach polyfill
  window.PointerEvent = PointerEventPolyfill
  // @ts-expect-error attach polyfill
  globalThis.PointerEvent = PointerEventPolyfill
}
