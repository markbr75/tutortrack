const NEW_LEDGERS = new Set(["sage", "freeagent"]);

/** Provider names, including the Phase 3 ledgers (E23-T10). */
export function providerName(t: (key: string) => string, provider: string): string {
  return NEW_LEDGERS.has(provider)
    ? t(`accountingPhase3.providers.${provider}`)
    : t(`accounting.providers.${provider}`);
}
