import type { JobProgressResponse, SelectedCandidates, VehicleResolveResponse } from "@/lib/api-types";

const FLOW_STATE_KEY = "koubei-demo-flow";

export type FlowState = {
  accessVersion: string | null;
  vehicleQuery: string | null;
  vehicleResolve: VehicleResolveResponse | null;
  selectedCandidates: SelectedCandidates | null;
  jobId: string | null;
  jobProgress: JobProgressResponse | null;
};

const initialState: FlowState = {
  accessVersion: null,
  vehicleQuery: null,
  vehicleResolve: null,
  selectedCandidates: null,
  jobId: null,
  jobProgress: null,
};

function readState(): FlowState {
  if (typeof window === "undefined") {
    return initialState;
  }

  const raw = window.sessionStorage.getItem(FLOW_STATE_KEY);
  if (!raw) {
    return initialState;
  }

  try {
    return { ...initialState, ...(JSON.parse(raw) as Partial<FlowState>) };
  } catch {
    return initialState;
  }
}

function writeState(state: FlowState) {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(FLOW_STATE_KEY, JSON.stringify(state));
}

export function getFlowState() {
  return readState();
}

export function setFlowState(patch: Partial<FlowState>) {
  writeState({ ...readState(), ...patch });
}

export function clearFlowState() {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.removeItem(FLOW_STATE_KEY);
}
