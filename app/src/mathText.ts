/**
 * Models love to emit LaTeX ($...$, $$...$$) and `#` headings, which show up as raw
 * symbols. Turn them into plain markdown (italics / bold) with unicode math before rendering.
 * Code (fenced or inline) is never touched.
 */

const SYMBOLS: Record<string, string> = {
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", epsilon: "ε", varepsilon: "ε", zeta: "ζ",
  eta: "η", theta: "θ", vartheta: "ϑ", iota: "ι", kappa: "κ", lambda: "λ", mu: "μ", nu: "ν",
  xi: "ξ", pi: "π", rho: "ρ", sigma: "σ", tau: "τ", upsilon: "υ", phi: "φ", varphi: "φ",
  chi: "χ", psi: "ψ", omega: "ω", Gamma: "Γ", Delta: "Δ", Theta: "Θ", Lambda: "Λ", Xi: "Ξ",
  Pi: "Π", Sigma: "Σ", Phi: "Φ", Psi: "Ψ", Omega: "Ω",
  cdot: "·", times: "×", div: "÷", pm: "±", mp: "∓", ast: "∗", circ: "∘", bullet: "•",
  leq: "≤", le: "≤", geq: "≥", ge: "≥", neq: "≠", ne: "≠", approx: "≈", equiv: "≡",
  sim: "∼", simeq: "≃", propto: "∝", ll: "≪", gg: "≫",
  to: "→", rightarrow: "→", leftarrow: "←", leftrightarrow: "↔", Rightarrow: "⇒",
  Leftarrow: "⇐", Leftrightarrow: "⇔", implies: "⇒", iff: "⇔", mapsto: "↦",
  infty: "∞", partial: "∂", nabla: "∇", forall: "∀", exists: "∃", in: "∈", notin: "∉",
  subset: "⊂", subseteq: "⊆", supset: "⊃", supseteq: "⊇", cup: "∪", cap: "∩",
  emptyset: "∅", varnothing: "∅", neg: "¬", land: "∧", lor: "∨", wedge: "∧", vee: "∨",
  sum: "∑", prod: "∏", int: "∫", oint: "∮", sqrt: "√", angle: "∠", degree: "°",
  ldots: "…", cdots: "⋯", dots: "…", vdots: "⋮", ddots: "⋱", prime: "′",
  hbar: "ℏ", ell: "ℓ", Re: "ℜ", Im: "ℑ", aleph: "ℵ", mathbb: "", langle: "⟨", rangle: "⟩",
  lfloor: "⌊", rfloor: "⌋", lceil: "⌈", rceil: "⌉", quad: " ", qquad: "  ",
};

const SUPERSCRIPT: Record<string, string> = {
  "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸",
  "9": "⁹", "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾", n: "ⁿ", i: "ⁱ", x: "ˣ",
  y: "ʸ", a: "ᵃ", b: "ᵇ", c: "ᶜ", d: "ᵈ", e: "ᵉ", f: "ᶠ", g: "ᵍ", h: "ʰ", j: "ʲ", k: "ᵏ",
  l: "ˡ", m: "ᵐ", o: "ᵒ", p: "ᵖ", r: "ʳ", s: "ˢ", t: "ᵗ", u: "ᵘ", v: "ᵛ", w: "ʷ", z: "ᶻ",
};

const SUBSCRIPT: Record<string, string> = {
  "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈",
  "9": "₉", "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎", a: "ₐ", e: "ₑ", h: "ₕ",
  i: "ᵢ", j: "ⱼ", k: "ₖ", l: "ₗ", m: "ₘ", n: "ₙ", o: "ₒ", p: "ₚ", r: "ᵣ", s: "ₛ", t: "ₜ",
  u: "ᵤ", v: "ᵥ", x: "ₓ",
};

/** Index of the brace that closes the one opened at `open`, or -1. */
function matchBrace(s: string, open: number): number {
  let depth = 0;
  for (let i = open; i < s.length; i++) {
    if (s[i] === "\\") i++;
    else if (s[i] === "{") depth++;
    else if (s[i] === "}" && --depth === 0) return i;
  }
  return -1;
}

/** Read one LaTeX argument at `i` (a {group} or a single char). */
function readArg(s: string, i: number): { text: string; end: number } | null {
  while (s[i] === " ") i++;
  if (i >= s.length) return null;
  if (s[i] === "{") {
    const close = matchBrace(s, i);
    if (close < 0) return { text: s.slice(i + 1), end: s.length };
    return { text: s.slice(i + 1, close), end: close + 1 };
  }
  if (s[i] === "\\") {
    const m = s.slice(i).match(/^\\[A-Za-z]+/);
    if (m) return { text: m[0], end: i + m[0].length };
  }
  return { text: s[i], end: i + 1 };
}

function script(text: string, map: Record<string, string>, marker: string): string {
  const chars = [...text];
  if (chars.every((c) => map[c] !== undefined)) return chars.map((c) => map[c]).join("");
  return chars.length === 1 ? `${marker}${text}` : `${marker}(${text})`;
}

function wrapIfCompound(s: string): string {
  return /^[\p{L}\p{N}.]+$/u.test(s) || /^\(.*\)$/.test(s) ? s : `(${s})`;
}

export function latexToText(src: string): string {
  let s = src;
  // Environments / sizing that carry no content of their own.
  s = s
    .replace(/\\(?:left|right|big|Big|bigg|Bigg|displaystyle|textstyle)\b\s*/g, "")
    .replace(/\\[,;:! ]/g, " ")
    .replace(/\\\\/g, "; ")
    .replace(/&/g, " ");

  let out = "";
  for (let i = 0; i < s.length; ) {
    const ch = s[i];
    if (ch === "\\") {
      const m = s.slice(i).match(/^\\([A-Za-z]+)/);
      if (!m) {
        // \{ \} \% \$ \_ \# \& and friends: keep the literal character
        out += s[i + 1] ?? "";
        i += 2;
        continue;
      }
      const cmd = m[1];
      i += m[0].length;
      if (cmd === "frac" || cmd === "dfrac" || cmd === "tfrac") {
        const a = readArg(s, i);
        const b = a && readArg(s, a.end);
        if (a && b) {
          out += `${wrapIfCompound(latexToText(a.text))}/${wrapIfCompound(latexToText(b.text))}`;
          i = b.end;
          continue;
        }
      } else if (cmd === "sqrt") {
        let root = "";
        if (s[i] === "[") {
          const close = s.indexOf("]", i);
          if (close > 0) {
            root = latexToText(s.slice(i + 1, close));
            i = close + 1;
          }
        }
        const a = readArg(s, i);
        if (a) {
          const inner = latexToText(a.text);
          const prefix = root ? script(root, SUPERSCRIPT, "^") : "";
          out += `${prefix}√${/^[\w.]+$/.test(inner) ? inner : `(${inner})`}`;
          i = a.end;
          continue;
        }
      } else if (
        ["text", "mathrm", "mathbf", "mathit", "mathbb", "mathcal", "operatorname", "textbf", "textit", "mbox", "boldsymbol", "vec", "bar", "hat", "tilde", "overline"].includes(cmd)
      ) {
        const a = readArg(s, i);
        if (a) {
          const inner = latexToText(a.text);
          out += cmd === "vec" ? `${inner}⃗` : cmd === "hat" ? `${inner}̂` : cmd === "bar" || cmd === "overline" ? `${inner}̄` : inner;
          i = a.end;
          continue;
        }
      } else if (cmd in SYMBOLS) {
        out += SYMBOLS[cmd];
        continue;
      } else if (/^(sin|cos|tan|cot|sec|csc|log|ln|exp|lim|max|min|sup|inf|det|dim|gcd|arg|deg|mod|sinh|cosh|tanh|arcsin|arccos|arctan)$/.test(cmd)) {
        out += cmd;
        continue;
      }
      out += cmd; // unknown command: show its name rather than a backslash
      continue;
    }
    if (ch === "^" || ch === "_") {
      const a = readArg(s, i + 1);
      if (a) {
        out += script(latexToText(a.text), ch === "^" ? SUPERSCRIPT : SUBSCRIPT, ch);
        i = a.end;
        continue;
      }
    }
    if (ch === "{" || ch === "}") {
      i++;
      continue;
    }
    out += ch;
    i++;
  }
  return out.replace(/[ \t]{2,}/g, " ").trim();
}

/** Escape characters markdown would eat inside our italic wrapper. */
function italic(text: string): string {
  const t = text.replace(/\*/g, "∗").replace(/_/g, "\\_");
  return t ? `*${t}*` : "";
}

function convertMath(text: string): string {
  let s = text;
  // $$ ... $$ and \[ ... \]  → own paragraph (an unterminated $$ at the end still counts)
  s = s.replace(/\$\$([\s\S]*?)(?:\$\$|$)/g, (_, body: string) => {
    const t = latexToText(body);
    return t ? `\n\n${italic(t.replace(/\s*\n\s*/g, " "))}\n\n` : "";
  });
  s = s.replace(/\\\[([\s\S]*?)(?:\\\]|$)/g, (_, body: string) => {
    const t = latexToText(body);
    return t ? `\n\n${italic(t.replace(/\s*\n\s*/g, " "))}\n\n` : "";
  });
  // \( ... \)
  s = s.replace(/\\\(([\s\S]*?)\\\)/g, (_, body: string) => italic(latexToText(body)));
  // $ ... $ — not currency: no space just inside, closing $ not followed by a digit
  s = s.replace(
    /(?<![\\$\w])\$(?!\s)((?:\\.|[^$\n\\])+?)(?<!\s)\$(?![\d$])/g,
    (_, body: string) => italic(latexToText(body))
  );
  return s;
}

function convertHeadings(text: string): string {
  return text.replace(/^[ \t]{0,3}#{1,6}[ \t]*(?=[^\s#\d])(.+?)[ \t]*#*[ \t]*$/gm, (_, title: string) => {
    const t = title.replace(/\*\*/g, "").trim();
    return t ? `**${t}**` : "";
  });
}

/** Apply fn to everything outside ``` fences and `inline code`. */
function outsideCode(text: string, fn: (plain: string) => string): string {
  const parts = text.split(/(```[\s\S]*?(?:```|$)|`[^`\n]+`)/g);
  return parts.map((p, i) => (i % 2 === 1 ? p : fn(p))).join("");
}

export function renderMathAndHeadings(text: string): string {
  if (!text || !/[$#\\]/.test(text)) return text;
  return outsideCode(text, (plain) => convertHeadings(convertMath(plain)));
}
