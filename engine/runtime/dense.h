/* Dense (Qwen2/Qwen3 / Llama / Mistral) path shared by kestrel-engine.
 * Same int8 attn + int4 MLP + SDOT IDOT family as the MoE path in engine.c. */
#ifndef KESTREL_DENSE_H
#define KESTREL_DENSE_H

/* 1 if SNAP/config.json looks like a dense GQA+SwiGLU causal LM (not MoE). */
int dense_is_arch(const char *snap);

/* Run dense generate using SNAP / PROMPT|COLI_PROMPT / NGEN env (same as MoE CLI). */
int dense_run(int argc, char **argv);

#endif
