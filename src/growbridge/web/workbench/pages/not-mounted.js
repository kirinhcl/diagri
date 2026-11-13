// A service that is not configured has no routes at all: the server answers a plain 404, with no refusal code.
import { ApiError } from "../api.js";

export function isNotMounted(error) {
  return error instanceof ApiError && error.status === 404 && !error.code;
}
