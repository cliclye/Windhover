/** Image attachments for Chat and Code (paste, drop, or pick a file). */

export type Attachment = {
  id: string;
  name: string;
  /** Sent to the model: downscaled so the longest side is at most MAX_SIDE. */
  dataUrl: string;
  /** Small preview for the transcript. */
  thumb: string;
};

const MAX_SIDE = 1600;
const THUMB_SIDE = 192;
export const MAX_ATTACHMENTS = 6;

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("not an image"));
    img.src = src;
  });
}

function readAsDataUrl(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

function render(img: HTMLImageElement, side: number, type: string, quality: number): string {
  const scale = Math.min(1, side / Math.max(img.naturalWidth, img.naturalHeight));
  const w = Math.max(1, Math.round(img.naturalWidth * scale));
  const h = Math.max(1, Math.round(img.naturalHeight * scale));
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#fff"; // transparent PNGs: flatten on white like the model expects
  ctx.fillRect(0, 0, w, h);
  ctx.drawImage(img, 0, 0, w, h);
  return c.toDataURL(type, quality);
}

export async function fileToAttachment(file: File): Promise<Attachment> {
  const src = await readAsDataUrl(file);
  const img = await loadImage(src);
  // PNG keeps screenshot text crisp; photos go out as JPEG.
  const big = img.naturalWidth * img.naturalHeight > 1_200_000 || file.type === "image/jpeg";
  return {
    id: Math.random().toString(36).slice(2, 10),
    name: file.name || "image",
    dataUrl: render(img, MAX_SIDE, big ? "image/jpeg" : "image/png", 0.92),
    thumb: render(img, THUMB_SIDE, "image/jpeg", 0.8),
  };
}

export function imageFiles(list: FileList | DataTransferItemList | null | undefined): File[] {
  if (!list) return [];
  const out: File[] = [];
  for (let i = 0; i < list.length; i++) {
    const it = list[i] as File | DataTransferItem;
    if (it instanceof File) {
      if (it.type.startsWith("image/")) out.push(it);
    } else if (it.kind === "file" && it.type.startsWith("image/")) {
      const f = it.getAsFile();
      if (f) out.push(f);
    }
  }
  return out;
}
