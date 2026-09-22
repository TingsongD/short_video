export function selectableBudget(b: Record<string, any>): boolean {
  return b.selection_eligible !== false && !b.retired && !String(b.id).startsWith('authority:');
}
