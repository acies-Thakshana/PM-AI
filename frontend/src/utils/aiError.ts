/** The AI service's own error is JSON with a plan name in it. The PM needs to know what happened and what to do. */
export function friendlyAiError(raw: string, fallback: string): string {
  if (/tokens per day|\bTPD\b/i.test(raw)) {
    return "The AI service has used up its allowance for today. It resets within a few minutes to an hour, or the limit on the AI service can be raised. Try again then.";
  }
  if (/\b413\b|tokens per minute|\bTPM\b|rate limit|\b429\b/i.test(raw)) {
    return "The AI service turned this request down because of its usage limit. Wait a minute and try again. If it keeps happening, the limit on the AI service needs to be raised.";
  }
  return fallback;
}
