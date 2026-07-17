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

  await call("Page.bringToFront");
  await call("Page.reload", { ignoreCache: true });
  await new Promise((resolve) => setTimeout(resolve, 7000));
  const result = await call("Runtime.evaluate", {
    expression: `JSON.stringify({
      summary: document.querySelector("#channelSummary")?.textContent || "",
      cards: document.querySelectorAll(".card").length,
      status: document.querySelector("#status")?.textContent || "",
      gridTop: Math.round(document.querySelector("#grid")?.getBoundingClientRect().top || 0),
      viewportHeight: window.innerHeight,
      channelOptions: Math.max(0, document.querySelectorAll("#channel option").length - 1),
      disabledChannelOptions: document.querySelectorAll("#channel option:disabled").length,
      containsExcludedChannel: [...document.querySelectorAll("#channel option")]
        .some((item) => item.textContent.includes("俺たちの馴れ初め")),
      images: (() => {
        const items = [...document.querySelectorAll(".card img")];
        return {
          total: items.length,
          loaded: items.filter((item) => item.complete && item.naturalWidth > 0).length,
          placeholders: items.filter((item) => item.src.startsWith("data:image/svg+xml")).length,
          gcs: items.filter((item) => item.src.includes("storage.googleapis.com")).length,
          youtube: items.filter((item) => item.src.includes("ytimg.com")).length,
        };
      })(),
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
      const select = document.querySelector("#channel");
      const option = [...select.options].find((item) => item.value && !item.disabled);
      if (!option) return JSON.stringify({ selected: false });
      select.value = option.value;
      render();
      return JSON.stringify({
        selected: true,
        selectedChannel: select.value,
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
  console.log(JSON.stringify({ initial, filtered }));
  if (initial.channelOptions !== 32) throw new Error(`registry-option-count:${initial.channelOptions}`);
  if (initial.disabledChannelOptions !== 2) throw new Error(`no-data-option-count:${initial.disabledChannelOptions}`);
  if (initial.containsExcludedChannel) throw new Error("excluded-channel-option");
  if (initial.unexpectedVideoChannels.length) {
    throw new Error(`out-of-scope-video-channels:${initial.unexpectedVideoChannels.join(",")}`);
  }
  if (!initial.fallbackTerminates) throw new Error("thumbnail-fallback-loop");
  if (!initial.status.includes("32ch")) throw new Error("scope-status-label");
  if (initial.gridTop >= initial.viewportHeight) throw new Error(`video-grid-below-fold:${initial.gridTop}`);
  if (!initial.images.loaded) throw new Error("no-loaded-thumbnails");
  if (!filtered.selected || !filtered.selectedChannel) throw new Error("channel-filter");
}

main().catch((error) => {
  console.error(`ERROR:${String(error)}`);
  process.exitCode = 1;
});
