export interface SearchHit {
  product_id: number;
  product_name: string;
  product_class: string | null;
  category_hierarchy: string | null;
  average_rating: number | null;
  review_count: number | null;
  score: number;
}

export interface SearchResponse {
  hits: SearchHit[];
  embed_ms: number;
  db_ms: number;
  total_ms: number;
  mode: 'semantic' | 'hybrid';
  cache_hit?: boolean;
}

export interface ProductDetail {
  product_id: number;
  product_name: string;
  product_class: string | null;
  category_hierarchy: string | null;
  product_description: string | null;
  product_features: string | null;
  average_rating: number | null;
  review_count: number | null;
}

export interface ClassFacet {
  product_class: string;
  n: number;
}

export type AppMode = 'standard' | 'turbo';

const base = '';

function searchPath(appMode: AppMode): string {
  return appMode === 'turbo' ? '/api/search/fast' : '/api/search';
}

function similarPath(productId: number, appMode: AppMode): string {
  return appMode === 'turbo'
    ? `/api/product/${productId}/similar/fast`
    : `/api/product/${productId}/similar`;
}

export async function search(
  params: {
    q: string;
    mode: 'semantic' | 'hybrid';
    product_class?: string | null;
    limit?: number;
  },
  appMode: AppMode = 'standard',
): Promise<SearchResponse> {
  const res = await fetch(`${base}${searchPath(appMode)}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      q: params.q,
      mode: params.mode,
      product_class: params.product_class ?? null,
      limit: params.limit ?? 20,
    }),
  });
  if (!res.ok) throw new Error(`search failed: ${res.status}`);
  return res.json();
}

export async function getProduct(id: number): Promise<ProductDetail> {
  const res = await fetch(`${base}/api/product/${id}`);
  if (!res.ok) throw new Error(`product ${id} not found`);
  return res.json();
}

export async function getSimilar(
  id: number,
  limit = 8,
  appMode: AppMode = 'standard',
): Promise<SearchHit[]> {
  const res = await fetch(`${base}${similarPath(id, appMode)}?limit=${limit}`);
  if (!res.ok) throw new Error(`similar failed`);
  return res.json();
}

export async function listClasses(): Promise<ClassFacet[]> {
  const res = await fetch(`${base}/api/classes?limit=30`);
  if (!res.ok) throw new Error('classes failed');
  return res.json();
}

export interface CacheStats {
  size: number;
  maxsize: number;
  hits: number;
  misses: number;
  hit_ratio_pct: number;
}

export async function getCacheStats(): Promise<CacheStats> {
  const res = await fetch(`${base}/api/cache/stats`);
  if (!res.ok) throw new Error('cache stats failed');
  return res.json();
}
