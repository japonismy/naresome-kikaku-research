const endpoint = process.argv[2] || "http://127.0.0.1:9333";
const targetFragment = process.argv[3] || "127.0.0.1:8765";

async function main() {
  const pages = await (await fetch(`${endpoint}/json`)).json();
  const page = pages.find((item) => item.url.includes(targetFragment));
  if (!page) throw new Error("target-not-found");

  const ws = new WebSocket(page.webSocketDebuggerUrl);
  let sequence = 0;
  const pending = new Map();
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (!message.id || !pending.has(message.id)) return;
    const request = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) request.reject(message.error);
    else request.resolve(message.result);
  };
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  const call = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  await new Promise((resolve) => setTimeout(resolve, 7000));
  const result = await call("Runtime.evaluate", {
    expression: `JSON.stringify({
      summary: document.querySelector("#channelSummary")?.textContent || "",
      rows: document.querySelectorAll("#channelTable tr").length,
      cards: document.querySelectorAll(".card").length,
      status: document.querySelector("#status")?.textContent || "",
      dbData: document.querySelectorAll(".data-pill.db").length,
      savedData: document.querySelectorAll(".data-pill.saved").length,
      noData: document.querySelectorAll(".data-pill.no").length,
      disabledFilters: document.querySelectorAll(".channel-filter:disabled").length,
      fallbackTerminates: (() => {
        const img = document.createElement("img");
        const video = {
          thumbnail_saved_url: "https://invalid.example/a.jpg",
          thumbnail_max_url: "https://invalid.example/b.jpg",
          thumbnail_fallback_urls: ["https://invalid.example/b.jpg", "https://invalid.example/c.jpg"],
        };
        applyThumbnail(img, video);
        for (let i = 0; i < thumbnailCandidates(video).length; i += 1) {
          fallbackImageForVideo(img, video);
        }
        return img.src.startsWith("data:image/svg+xml") && img.onerror === null;
      })(),
      unexpectedVideoChannels: (() => {
        const allowed = new Set(channels.map((channel) => channel.channel_id));
        const normalize = (value) => String(value || "").normalize("NFKC").toLowerCase().replace(/\\s+/g, "");
        const allowedTitles = new Set(channels.flatMap((channel) => [
          channel.channel_name,
          channel.db_title,
          channel.portal_channel_name,
        ]).map(normalize).filter(Boolean));
        return [...new Set(videos
          .filter((video) => !allowed.has(video.channel_id) && !allowedTitles.has(normalize(video.channel)))
          .map((video) => (video.channel_id || "") + ":" + (video.channel || "")))];
      })()
    })`,
    returnByValue: true,
  });
  const filterResult = await call("Runtime.evaluate", {
    expression: `(() => {
      const button = document.querySelector(".channel-filter:not(:disabled)");
      if (!button) return JSON.stringify({ clicked: false });
      button.click();
      return JSON.stringify({
        clicked: true,
        selectedChannel: document.querySelector("#channel")?.value || "",
        cards: document.querySelectorAll(".card").length,
        status: document.querySelector("#status")?.textContent || ""
      });
    })()`,
    returnByValue: true,
  });
  ws.close();
  const value = result?.result?.value;
  const filteredValue = filterResult?.result?.value;
  if (!value || !filteredValue) throw new Error("empty-evaluation-result");
  const initial = JSON.parse(value);
  const filtered = JSON.parse(filteredValue);
  if (initial.rows !== 32) throw new Error(`registry-row-count:${initial.rows}`);
  if (initial.dbData + initial.savedData + initial.noData !== 32) {
    throw new Error("registry-status-count");
  }
  if (initial.unexpectedVideoChannels.length) {
    throw new Error(`out-of-scope-video-channels:${initial.unexpectedVideoChannels.join(",")}`);
  }
  if (!initial.fallbackTerminates) throw new Error("thumbnail-fallback-loop");
  if (!initial.status.includes("32ch")) throw new Error("scope-status-label");
  if (!filtered.clicked || !filtered.selectedChannel) throw new Error("channel-filter");
  console.log(JSON.stringify({
    initial,
    filtered,
  }));
}

main().catch((error) => {
  console.error(`ERROR:${String(error)}`);
  process.exitCode = 1;
});
