/* Windhover runtime — dense KPK packs (mmap + sparse working set).
 * See runtime/windhover.c and tools/kestrel_pack.py. */
#ifndef KESTREL_WINDHOVER_H
#define KESTREL_WINDHOVER_H

/* 1 if SNAP (or SNAP/kpk) is a Windhover KPK pack. */
int wh_can_run(const char *snap);

/* Run generate using SNAP / PROMPT|COLI_PROMPT / NGEN env (same CLI contract
 * as the MoE and legacy dense paths). SERVE=1 keeps the pack loaded and reads
 * WHGEN turns from stdin (see tools/engine_session.py). */
int wh_run(int argc, char **argv);

#endif
