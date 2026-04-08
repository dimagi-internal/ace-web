type Envelope<T> = { data: T | null; error: { code: string; message: string } | null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  const body = (await res.json()) as Envelope<T>
  if (body.error) {
    throw new Error(body.error.message)
  }
  return body.data as T
}

export const api = {
  health: () => request<{ status: string }>("/health"),
}
