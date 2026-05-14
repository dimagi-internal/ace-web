import createClient from "openapi-fetch";
import type { paths } from "./generated";

const baseUrl = import.meta.env.BASE_URL || "/";
export const apiV2 = createClient<paths>({
  baseUrl: `${baseUrl.replace(/\/$/, "")}/api/v2`,
  credentials: "include",
  headers: {
    "X-Requested-With": "XMLHttpRequest",
  },
});
