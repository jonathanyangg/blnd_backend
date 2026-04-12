Deno.serve(async () => {
  const backendUrl = Deno.env.get("BACKEND_URL");
  const digestKey = Deno.env.get("DIGEST_API_KEY");

  if (!backendUrl || !digestKey) {
    return new Response(
      JSON.stringify({ error: "BACKEND_URL and DIGEST_API_KEY must be set" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  const response = await fetch(`${backendUrl}/notifications/send-weekly-digest`, {
    method: "POST",
    headers: {
      "X-Digest-Key": digestKey,
      "Content-Type": "application/json",
    },
  });

  const body = await response.text();

  return new Response(
    JSON.stringify({ status: response.status, body }),
    {
      status: response.ok ? 200 : 502,
      headers: { "Content-Type": "application/json" },
    },
  );
});
