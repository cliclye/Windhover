import { useEffect, useRef, useState, type RefObject } from "react";

/**
 * Local models emit text in bursts. While `active`, reveal `target` a few characters per
 * frame (faster the bigger the backlog) so it flows like a typewriter instead of jumping.
 * Text that was never streamed (history, finished replies) is returned untouched, and a
 * reveal already under way keeps running until it catches up even after `active` drops.
 */
export function useSmoothText(target: string, active: boolean): string {
  const [shown, setShown] = useState(active ? 0 : target.length);
  const animating = useRef(active);
  const targetRef = useRef(target);
  targetRef.current = target;
  if (active) animating.current = true;

  useEffect(() => {
    if (!animating.current) return;
    let raf = 0;
    let last = performance.now();
    const step = (now: number) => {
      const dt = Math.min(64, now - last);
      last = now;
      const full = targetRef.current.length;
      setShown((cur) => {
        if (cur > full) return full; // reply was replaced/regenerated
        if (cur === full) return cur;
        const backlog = full - cur;
        const perFrame = Math.max(1, Math.ceil(backlog * 0.06 * (dt / 16)));
        let next = Math.min(full, cur + perFrame);
        // don't split a surrogate pair
        const c = targetRef.current.charCodeAt(next - 1);
        if (next < full && c >= 0xd800 && c <= 0xdbff) next++;
        return next;
      });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [active]);

  // Caught up and no longer streaming: stop animating so later edits show instantly.
  useEffect(() => {
    if (!active && shown >= target.length) animating.current = false;
  }, [active, shown, target.length]);

  if (!animating.current) return target;
  return target.slice(0, Math.min(shown, target.length));
}

/**
 * Keep a scroll container pinned to the bottom while content grows, unless the user
 * scrolled up to read. `force` (e.g. the user just sent a message) always re-pins.
 */
export function useFollowBottom(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  changeKey: unknown,
  force: boolean
) {
  const stuck = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (force) stuck.current = true;
    if (stuck.current) el.scrollTop = el.scrollHeight;
  }, [ref, changeKey, force]);

  useEffect(() => {
    if (!active) return;
    let raf = 0;
    const tick = () => {
      const el = ref.current;
      if (el && stuck.current) el.scrollTop = el.scrollHeight;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [ref, active]);
}
