/**
 * 高阶函数：封装 setLoading / try / catch / finally 模板。
 * 用法：await withLoading(loadingMap, "key", async () => { ... })
 */
export async function withLoading(loadingMap, key, fn) {
  loadingMap[key] = true;
  try {
    return await fn();
  } catch (err) {
    throw err;
  } finally {
    loadingMap[key] = false;
  }
}
