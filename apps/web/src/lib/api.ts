export interface SampleJob {
  job_id: string;
  title: string;
  description: string;
  required_skills: string[];
  budget: {
    min: number;
    max: number;
    currency: string;
  };
  duration_days: number | null;
  screening_questions: string[];
  warning_signals: string[];
  connects_cost: number | null;
  client_id: string | null;
  posted_at_hour: number | null;
  category: string | null;
  data_kind: "synthetic";
}

export type GraphState = Record<string, unknown>;

export interface GraphRunResult {
  status: "interrupted" | "completed" | "running";
  state: GraphState;
  interrupts: unknown[];
}

export interface MarketplaceMessage {
  message_id: string;
  proposal_id: string;
  job_id: string;
  sender: "client" | "freelancer";
  body: string;
  sent_at_hour: number;
}

export type ProposalStatus = "draft" | "submitted" | "viewed" | "replied" | "interview" | "hired" | "lost";

export interface PipelineProposal {
  proposal_id: string;
  job_id: string;
  status: ProposalStatus;
  price: number;
  connects_spent: number;
  created_at_hour: number;
  updated_at_hour: number;
}

export interface PipelineSnapshot {
  connects_balance: number;
  proposals: PipelineProposal[];
}

export interface PortfolioEvidence {
  id: string;
  freelancer_id: string | null;
  title: string;
  type: "cv" | "case_study" | "repo_readme" | "code" | "review" | "proposal";
  source: string;
  date: string | null;
  outcome: string | null;
  project: string | null;
  client_industry: string | null;
  skills: string[];
  content: string;
  data_kind: "real" | "synthetic" | "unverified";
}

interface StreamFrame {
  event: string;
  data: string;
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  const text = await response.text();
  try {
    const detail: unknown = JSON.parse(text).detail;
    if (typeof detail === "string") return detail;
  } catch {
    // Not JSON; fall through to the raw text.
  }
  return text || `${fallback} (${response.status})`;
}

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`);
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function getJobs(query = ""): Promise<SampleJob[]> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("query", query.trim());
  const encodedParams = params.toString();
  const suffix = encodedParams ? `?${encodedParams}` : "";
  return requestJson<SampleJob[]>(`/jobs${suffix}`);
}

export function getJob(jobId: string): Promise<SampleJob> {
  return requestJson<SampleJob>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function getBidRun(threadId: string): Promise<GraphRunResult> {
  return requestJson<GraphRunResult>(`/graphs/bid/${encodeURIComponent(threadId)}`);
}

export function getMessages(): Promise<MarketplaceMessage[]> {
  return requestJson<MarketplaceMessage[]>("/messages");
}

export function getPipeline(): Promise<PipelineSnapshot> {
  return requestJson<PipelineSnapshot>("/pipeline");
}

export async function searchPortfolio(query: string): Promise<PortfolioEvidence[]> {
  const params = new URLSearchParams({ query });
  const response = await fetch(`/api/portfolio/search?${params}`);
  if (!response.ok) throw new Error(await errorMessage(response, "Portfolio search failed"));
  return (await response.json()) as PortfolioEvidence[];
}

export function getConversationRun(threadId: string): Promise<GraphRunResult> {
  return requestJson<GraphRunResult>(`/graphs/conversation/${encodeURIComponent(threadId)}`);
}

export async function startConversation(
  threadId: string, message: MarketplaceMessage,
): Promise<GraphRunResult> {
  const response = await fetch("/api/graphs/conversation/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      thread_id: threadId,
      input: { conversation_id: message.proposal_id, client_message: message.body },
    }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Drafting failed"));
  return (await response.json()) as GraphRunResult;
}

export async function reviewConversation(
  threadId: string, action: "approve" | "reject" | "edit", message?: string,
): Promise<GraphRunResult> {
  const response = await fetch(`/api/graphs/conversation/${encodeURIComponent(threadId)}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...(message !== undefined && { message }) }),
  });
  if (!response.ok) throw new Error(await errorMessage(response, "Review failed"));
  return (await response.json()) as GraphRunResult;
}

export async function continueBid(threadId: string): Promise<GraphRunResult> {
  const response = await fetch(`/api/graphs/bid/${encodeURIComponent(threadId)}/continue`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Continue failed"));
  }
  return (await response.json()) as GraphRunResult;
}

export async function reviewBid(
  threadId: string,
  action: "approve" | "reject" | "edit",
  coverLetter?: string,
  screeningAnswers?: string[],
): Promise<GraphRunResult> {
  const response = await fetch(`/api/graphs/bid/${encodeURIComponent(threadId)}/approval`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      ...(coverLetter !== undefined && { cover_letter: coverLetter }),
      ...(screeningAnswers !== undefined && { screening_answers: screeningAnswers }),
    }),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response, "Review failed"));
  }
  return (await response.json()) as GraphRunResult;
}

function parseFrame(frame: string): StreamFrame | undefined {
  let event = "message";
  const data: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, data: data.join("\n") } : undefined;
}

export async function streamBidAnalysis(
  job: SampleJob,
  threadId: string,
  onUpdate: (nodeNames: string[], update: GraphState) => void,
): Promise<GraphRunResult> {
  const response = await fetch("/api/graphs/bid/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      thread_id: threadId,
      input: { job },
    }),
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Analysis request failed (${response.status})`);
  }
  if (!response.body) {
    throw new Error("The browser could not open the analysis event stream.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalStatus: GraphRunResult["status"] | undefined;
  const combinedState: GraphState = {};
  const interrupts: unknown[] = [];

  const handleFrame = (rawFrame: string) => {
    const frame = parseFrame(rawFrame);
    if (!frame) return;
    const payload: unknown = JSON.parse(frame.data);

    if (frame.event === "error") {
      const detail =
        typeof payload === "object" && payload !== null && "detail" in payload
          ? String(payload.detail)
          : "Analysis failed.";
      throw new Error(detail);
    } else if (frame.event === "update" && typeof payload === "object" && payload !== null) {
      const update = payload as GraphState;
      const names = Object.keys(update);
      for (const value of Object.values(update)) {
        if (typeof value === "object" && value !== null && !Array.isArray(value)) {
          Object.assign(combinedState, value);
        }
      }
      if ("__interrupt__" in update) {
        interrupts.push(update.__interrupt__);
        finalStatus = "interrupted";
      }
      onUpdate(names, update);
    } else if (frame.event === "complete" && typeof payload === "object" && payload !== null) {
      const status = (payload as { status?: string }).status;
      if (status === "interrupted" || status === "completed") finalStatus = status;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      handleFrame(buffer.slice(0, separator));
      buffer = buffer.slice(separator + 2);
      separator = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (buffer.trim()) handleFrame(buffer);
  if (!finalStatus) {
    throw new Error("The analysis event stream ended before completion.");
  }

  return { status: finalStatus, state: combinedState, interrupts };
}
