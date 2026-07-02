import { safeGet, safePost } from "./client.js";

export const knowledgeApi = {
  buildKnowledge() {
    return safePost("/api/knowledge/build", {}, "buildKnowledge");
  },
  searchKnowledge(query, topK = 5) {
    return safeGet(
      "/api/knowledge/search",
      {
        params: {
          query,
          top_k: topK,
        },
      },
      "searchKnowledge"
    );
  },
};
