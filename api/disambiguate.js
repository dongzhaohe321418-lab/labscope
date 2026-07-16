// Vercel Serverless function — LLM disambiguation of instrument-paper links.
// The OpenAI key lives ONLY in the server-side env var OPENAI_API_KEY, never in
// the client. If the key is not configured the function returns 503 and the
// front-end silently falls back to its heuristic — so the static site keeps
// working with or without this endpoint.
//
// Configure in Vercel:  vercel env add OPENAI_API_KEY   (then redeploy)

module.exports = async (req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") { res.status(200).end(); return; }
  if (req.method !== "POST") { res.status(405).json({ error: "POST only" }); return; }

  const key = process.env.OPENAI_API_KEY;
  if (!key) { res.status(503).json({ error: "OPENAI_API_KEY not configured" }); return; }

  try {
    const { target, items } = req.body || {};
    if (!target || !Array.isArray(items) || !items.length) { res.status(400).json({ error: "bad request" }); return; }

    const listing = items.slice(0, 40)
      .map(it => `[${it.idx}] "${String(it.evidence || "").slice(0, 400)}"`)
      .join("\n");

    const r = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "gpt-4o-mini",
        temperature: 0,
        response_format: { type: "json_object" },
        messages: [
          { role: "system", content: 'You verify instrument usage in scientific papers. For each numbered excerpt, decide whether it describes USING the target instrument in the study (measurement, sampling, calibration, data collection) — NOT a coincidental token match (e.g. a laser wavelength like "405 nm", a figure label like "2B", the number 1600) and NOT a different product. Return JSON {"results":[{"idx":N,"used":true|false}]} covering every idx you were given.' },
          { role: "user", content: `Target instrument: ${target}\n\nExcerpts:\n${listing}` },
        ],
      }),
    });
    if (!r.ok) { res.status(502).json({ error: "openai " + r.status }); return; }
    const d = await r.json();
    const parsed = JSON.parse(d.choices[0].message.content);
    res.status(200).json({ results: Array.isArray(parsed.results) ? parsed.results : [] });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
};
