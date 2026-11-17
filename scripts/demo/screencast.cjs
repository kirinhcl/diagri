'use strict';
// Records a page through the Chrome DevTools screencast at device-pixel resolution and encodes it
// live with libx264 at a constant frame rate. Playwright's own recorder captures CSS pixels (a
// 1440x810 page stays 1440x810 inside the video) and encodes VP8 at about 1 Mbit/s, which blurs
// small text; this keeps the 4/3 device scale, so the frames are a sharp 1920x1080.
const { spawn } = require('child_process');

const FPS = 25;
const FRAME_MS = 1000 / FPS;

async function startScreencast(page, outFile, ffmpegPath, { width, height, quality = 92 }) {
  const cdp = await page.context().newCDPSession(page);
  const ff = spawn(ffmpegPath, [
    '-loglevel', 'error', '-y',
    '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-vf', `scale=${width}:${height}:flags=lanczos:force_original_aspect_ratio=decrease,`
      + `pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=0xf4f1e8,format=yuv420p`,
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17', '-r', String(FPS), '-movflags', '+faststart',
    outFile,
  ], { stdio: ['pipe', 'inherit', 'inherit'] });
  const exited = new Promise((resolve) => ff.on('close', resolve));
  ff.stdin.on('error', (error) => console.error('screencast: ffmpeg input closed:', error.message));

  let latest = null;
  cdp.on('Page.screencastFrame', ({ data, sessionId }) => {
    latest = Buffer.from(data, 'base64');
    cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', {
    format: 'jpeg', quality, maxWidth: width, maxHeight: height, everyNthFrame: 1,
  });

  // The screencast only sends a frame when the page changes; repeat the newest one on a wall-clock
  // grid so the video's time matches real time (the timeline marks depend on it).
  const start = Date.now();
  let written = 0;
  const timer = setInterval(() => {
    if (!latest) return;
    const due = Math.floor((Date.now() - start) / FRAME_MS);
    while (written <= due) {
      ff.stdin.write(latest);
      written += 1;
    }
  }, FRAME_MS / 2);

  return {
    start,
    async stop() {
      clearInterval(timer);
      await cdp.send('Page.stopScreencast').catch(() => {});
      ff.stdin.end();
      const code = await exited;
      if (code !== 0) throw new Error(`ffmpeg exited with ${code}`);
      return { frames: written, seconds: written / FPS };
    },
  };
}

module.exports = { startScreencast, FPS };
