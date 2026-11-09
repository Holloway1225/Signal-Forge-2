
(() => {
  const $ = id => document.getElementById(id);

  // Use the existing Lyric Architect in index.html.
  // Never create a duplicate section.
  const panel = $("lyricArchitect");

  if (!panel) {
    console.error("Lyric Architect section not found.");
    return;
  }

  const button = $("architectGenerate");
  const status = $("architectStatus");
  const results = $("architectResults");

  if (!button || !status || !results) {
    console.error("Lyric Architect elements missing.");
    return;
  }

  // Prevent accidental double initialization.
  if (button.dataset.initialized === "true") return;
  button.dataset.initialized = "true";

  button.addEventListener("click", async () => {
    const lyrics = $("architectLyrics").value.trim();
    const sound = $("architectSound").value.trim();

    const backend = $("backend").value
      .trim()
      .replace(/\/+$/, "");

    if (!lyrics) {
      status.textContent = "Paste your finished lyrics first.";
      return;
    }

    if (lyrics.length > 5000) {
      status.textContent =
        "Lyrics exceed 5,000 characters. Shorten them before generating.";
      return;
    }

    if (!backend || !/^https?:\/\//i.test(backend)) {
      status.textContent =
        "Enter your Render backend URL at the bottom of the page.";
      return;
    }

    const preserveLyrics = $("architectPreserve").checked;
    const addInstrumentals = $("architectInstrumentals").checked;

    button.disabled = true;
    status.textContent = "Architecting lyrics...";
    results.hidden = true;

    try {
      const response = await fetch(
        `${backend}/api/tag-lyrics`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            lyrics: lyrics,
            sound: sound,
            preserve_lyrics: preserveLyrics,
            add_instrumentals: addInstrumentals
          })
        }
      );

      const data = await response.json();

      if (!response.ok) {
        let message = `Server error ${response.status}`;

        if (typeof data.detail === "string") {
          message = data.detail;
        } else if (Array.isArray(data.detail)) {
          message = data.detail
            .map(item => item.msg || JSON.stringify(item))
            .join("; ");
        }

        throw new Error(message);
      }

      if (typeof data.tagged_lyrics !== "string") {
        throw new Error("Backend did not return tagged lyrics.");
      }

      $("architectOutput").textContent = data.tagged_lyrics;

      const count = data.tagged_lyrics.length;

      $("architectCount").textContent =
        `${count} / 5000 characters`;

      results.hidden = false;

      status.textContent =
        count > 5000
          ? "Lyrics generated, but output exceeds Suno's 5,000-character limit."
          : "Lyrics successfully architected.";

      results.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });

    } catch (error) {
      status.textContent = `Error: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  });

  $("architectCopy").addEventListener("click", async () => {
    const text = $("architectOutput").textContent;

    if (!text) return;

    try {
      await navigator.clipboard.writeText(text);
      status.textContent = "Copied to clipboard.";
    } catch {
      status.textContent =
        "Copy failed. Select the lyrics and copy manually.";
    }
  });
})();
