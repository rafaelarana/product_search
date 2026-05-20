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

const base = '';

export async function search(params: {
  q: string;
  mode: 'semantic' | 'hybrid';
  product_class?: string | null;
  limit?: number;
}): Promise<SearchResponse> {
  const res = await fetch(`${base}/api/search`, {
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

export async function getSimilar(id: number, limit = 8): Promise<SearchHit[]> {
  const res = await fetch(`${base}/api/product/${id}/similar?limit=${limit}`);
  if (!res.ok) throw new Error(`similar failed`);
  return res.json();
}

export async function listClasses(): Promise<ClassFacet[]> {
  const res = await fetch(`${base}/api/classes?limit=30`);
  if (!res.ok) throw new Error('classes failed');
  return res.json();
}
