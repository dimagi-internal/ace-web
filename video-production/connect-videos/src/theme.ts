// Brand tokens lifted from labs.connect.dimagi.com's :root CSS variables.
// Indigo/sky is the primary palette, mango is sparingly used for CTAs,
// ink/paper neutrals carry surfaces and text.
import { loadFont as loadWorkSans } from "@remotion/google-fonts/WorkSans";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";

const { fontFamily: workSansFamily } = loadWorkSans();
// Inter is loaded just for caption use — see CaptionBar. It reads cleaner
// than Work Sans at small caption sizes with a stroke applied; YouTube,
// TED, and most modern documentaries use Inter/Roboto for subtitles.
const { fontFamily: interFamily } = loadInter();

export const theme = {
  colors: {
    // Neutral surfaces
    background: "#FAFBFF",          // --paper
    surface: "#FFFFFF",             // --paper-2
    surfaceWarm: "#F5F6FB",         // --paper-warm
    surfaceCool: "#F0F3FF",         // --paper-cool / --sky-tint
    line: "#E6E7F0",                // --line
    rule: "#C9CCE0",                // --rule
    // Ink (text + dark surfaces)
    foreground: "#0A0620",          // --ink, deep navy/indigo
    foreground2: "#14103A",         // --ink-2
    foreground3: "#4A5468",         // --ink-3
    muted: "#6B7388",               // --muted
    // Indigo (primary brand)
    accent: "#3843D0",              // --indigo
    accentDeep: "#2832A0",          // --indigo-deep
    accentSoft: "#E7E9FB",          // --indigo-soft
    sky: "#8EA1FF",                 // --sky
    skyDeep: "#5C6FE8",             // --sky-deep
    // Mango (CTA only)
    mango: "#FC5F36",
    mangoDeep: "#E04A22",
    marigold: "#FEAF31",
    // Caption overlay
    captionBg: "#0A0620",
    captionFg: "#FFFFFF",
    // Legacy alias kept so existing imports referencing accentDark
    // still resolve until they're migrated to accentDeep.
    accentDark: "#2832A0",
  },
  gradients: {
    primary: "linear-gradient(135deg, #2832A0 0%, #3843D0 50%, #8EA1FF 100%)",
    text: "linear-gradient(90deg, #14103A 0%, #3843D0 55%, #5C6FE8 100%)",
    textOnDark: "linear-gradient(90deg, #FFFFFF 0%, #8EA1FF 100%)",
  },
  fonts: {
    sans: `${workSansFamily}, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif`,
    display: `${workSansFamily}, -apple-system, sans-serif`,
    // Used by CaptionBar — Inter for cleaner small-size rendering.
    caption: `${interFamily}, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif`,
  },
  radii: { xs: 8, sm: 14, md: 14, lg: 22 },
  spacing: { xs: 8, sm: 16, md: 24, lg: 48, xl: 96 },
} as const;

export type Theme = typeof theme;
