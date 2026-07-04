export interface CommentSubmitPayload {
  author?: { id?: string; name?: string };
  comment?: {
    id?: string;
    body?: string;
    author?: string;
    parentId?: string;
    postId?: string;
    permalink?: string;
  };
  subreddit?: { name?: string };
}

export interface ProcessFactcheckJobData {
  commentId: string;
  authorName: string | null;
  inlineBody: string;
  parentId?: string;
  postId?: string;
  permalink?: string;
}
