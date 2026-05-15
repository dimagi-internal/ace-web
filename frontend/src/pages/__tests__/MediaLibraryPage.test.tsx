import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import * as api from "@/api/videos";
import MediaLibraryPage from "@/pages/MediaLibraryPage";

describe("MediaLibraryPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "listMediaLibraryVideo").mockResolvedValue({
      subfolders: [
        {
          subfolder: "uganda",
          items: [
            {
              ref: "library:video/uganda/drone.mp4",
              drive_id: "abc",
              drive_url: "https://drive/abc",
              filename: "drone.mp4",
              name: "Drone",
              description: null,
              tags: ["uganda"],
              status: "ok",
            },
          ],
        },
      ],
    });
    vi.spyOn(api, "listMediaLibraryAudio").mockResolvedValue({
      items: [
        {
          hash: "h1",
          drive_id: "d1",
          drive_url: "https://drive/d1",
          voice_id: "v1",
          model: "m1",
          text: "Hello",
          duration_sec: 1.4,
          generated_at: "2026-05-15T00:00:00Z",
          status: "ok",
        },
      ],
    });
  });

  it("renders video subfolders by default", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws/videos/library"]}>
        <Routes>
          <Route path="/w/:workspaceSlug/videos/library" element={<MediaLibraryPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("heading", { name: "uganda" })).toBeInTheDocument();
    expect(await screen.findByText("Drone")).toBeInTheDocument();
  });

  it("switches to audio tab via ?type=audio", async () => {
    render(
      <MemoryRouter initialEntries={["/w/ws/videos/library?type=audio"]}>
        <Routes>
          <Route path="/w/:workspaceSlug/videos/library" element={<MediaLibraryPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Hello")).toBeInTheDocument();
    expect(await screen.findByText(/v1/)).toBeInTheDocument();
  });
});
