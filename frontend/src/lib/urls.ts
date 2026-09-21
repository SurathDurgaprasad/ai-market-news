/**
 * Defense-in-depth sanitizer for URLs that reach <a href> or <img src>.
 * The backend already rejects unsafe URLs; this keeps javascript:/data:/
 * private hosts from rendering if a bad value still arrives.
 */
const BLOCKED_PORTS = new Set([
  '22', '23', '25', '445', '1433', '3306', '3389', '5432', '6379', '11211', '27017',
]);

function isPrivateIpv4(host: string): boolean {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  if (a === 10 || a === 127 || a === 0) return true;
  if (a === 192 && b === 168) return true;
  if (a === 169 && b === 254) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 100 && b >= 64 && b <= 127) return true;
  return false;
}

export function safeHttpUrl(
  url?: string | null,
  opts?: { keepQuery?: boolean },
): string | undefined {
  if (!url || typeof url !== 'string') return undefined;
  const trimmed = url.trim();
  if (!/^https?:\/\//i.test(trimmed)) return undefined;
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return undefined;
    if (parsed.username || parsed.password) return undefined;
    const host = parsed.hostname.replace(/^\[|\]$/g, '').toLowerCase();
    if (!host) return undefined;
    if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) {
      return undefined;
    }
    if (host === '::1' || host === '0.0.0.0') return undefined;
    if (isPrivateIpv4(host)) return undefined;
    if (/^\d+$/.test(host) || host.startsWith('0x')) return undefined;
    if (parsed.port && BLOCKED_PORTS.has(parsed.port)) return undefined;
    if (!opts?.keepQuery) {
      parsed.search = '';
      parsed.hash = '';
    }
    return parsed.toString();
  } catch {
    return undefined;
  }
}
