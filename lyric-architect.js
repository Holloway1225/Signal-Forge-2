
(() => {
  const $ = id => document.getElementById(id);

  const panel = document.createElement("section");
  panel.className = "panel";
  panel.id = "lyricArchitect";

  panel.innerHTML = `
    <div class="section-title">04 / LYRIC ARCHITECT</div>
    <h2>AI Lyric Architect</h2>
    <p>Paste finished lyrics and add Suno production tags without rewriting your words.</p>

    <label>Finished lyrics
      <textarea id="architectLyrics" rows="14"
        placeholder="[Verse 1]&#10;Paste your lyrics here..."></textarea>
    </label>

    <label>Production style
      <textarea id="architectSound" rows="3"
        placeholder="Dark atmospheric alternative metal, intimate verses, crushing choruses, melodic guitar solo"></textarea>
    </label>

    <label class="check">
      <input id="architectPreserve" type="checkbox" checked>
      Preserve original lyrics
    </label>

    <label class="check">
      <input id="architectInstrumentals" type="checkbox" checked>
      Add instrumental sections
    </label>

    <button id="architectGenerate" class="primary" type="button">
      ARCHITECT LYRICS →
    </button>

    <div id="architectStatus" role="status" aria-live="polite"></div>

    <div id="architectResults" hidden>
      <div class="output-head">
        <h2>Suno-Ready Lyrics</h2>
        <button id="architectCopy" type="button">Copy</button>
      </div>
      <pre id="architectOutput" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre>
      <small id="architectCount"></small>
    </div>
  `;

  const footer = document.querySelector("footer");
  if (footer) footer.before(panel);
  else document.querySelector("main")?.append(panel);

  $("architectGenerate").addEventListener("click", async () => {
    const lyrics = $("architectLyrics").value.trim();
    const sound = $("architectSound").value.trim();
    const backend = $("backend")?.value.trim().replace(/\/+$/, "");
    const status = $("architectStatus");
    const button = $("architectGenerate");

    if (!lyrics) {
      status.textContent = "Paste your lyrics first.";
      return;
    }

    if (!backend || !/^https:\/\//i.test(backend)) {
      status.textContent = "Enter your HTTPS backend URL at the bottom of the page.";
      return;
    }

    button.disabled = true;
    status.textContent = "Architecting lyrics...";
    $("architectResults").hidden = true;

    try {
      const response = await fetch(`${backend}/api/tag-lyrics`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          lyrics,
          sound,
          preserve_lyrics: $("architectPreserve").checked,
          add_instrumentals: $("architectInstrumentals").checked
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(typeof data.detail === "string"
          ? data.detail : `Server error ${response.status}`);
      }

      if (typeof data.tagged_lyrics !== "string") {
        throw new Error("Missing tagged lyrics in response.");
      }

      $("architectOutput").textContent = data.tagged_lyrics;
      $("architectCount").textContent =
        `${data.tagged_lyrics.length} / 5000 characters`;

      $("architectResults").hidden = false;
      status.textContent = "Lyrics ready.";

    } catch (error) {
      status.textContent = `Error: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });

  $("architectCopy").addEventListener("click", async () => {
    const value = $("architectOutput").textContent;
    try {
      await navigator.clipboard.writeText(value);
      $("architectStatus").textContent = "Copied to clipboard.";
    } catch {
      $("architectStatus").textContent =
        "Copy failed. Select and copy the lyrics manually.";
    }
  });
})();
