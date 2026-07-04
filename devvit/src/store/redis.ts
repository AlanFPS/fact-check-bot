export interface RedisLike {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, opts?: { nx?: boolean }): Promise<string | null>;
  incrBy(key: string, n: number): Promise<number>;
  expire(key: string, seconds: number): Promise<void>;
  exists?(key: string): Promise<number>;
}
