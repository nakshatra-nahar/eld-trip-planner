// Typed fetch client for the RouteLog Django API.
import type {
  ApiError,
  GeocodeResponse,
  PlanRequest,
  PlanResponse,
  ReverseGeocodeResponse,
} from '../types/api'

/** Error thrown for any failed request. `code` mirrors ApiError.code, plus client-side codes. */
export class ApiRequestError extends Error {
  readonly code: string
  readonly status: number
  readonly details?: Record<string, string[]>

  constructor(message: string, code: string, status: number, details?: Record<string, string[]>) {
    super(message)
    this.name = 'ApiRequestError'
    this.code = code
    this.status = status
    this.details = details
  }
}

export interface ApiClient {
  planTrip(request: PlanRequest, signal?: AbortSignal): Promise<PlanResponse>
  geocode(query: string, signal?: AbortSignal): Promise<GeocodeResponse>
  reverse(lat: number, lon: number, signal?: AbortSignal): Promise<ReverseGeocodeResponse>
}

function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as ApiError).error === 'string' &&
    typeof (value as ApiError).code === 'string'
  )
}

const FALLBACK_MESSAGES: Record<number, string> = {
  400: 'Some of the trip details are invalid.',
  404: 'The planning service could not be found.',
  422: 'No drivable route was found between these locations.',
  429: 'Too many requests. Please wait a moment and try again.',
  502: 'The routing service is temporarily unavailable.',
  503: 'The planning service is temporarily unavailable.',
  504: 'The planning service took too long to respond.',
}

export function createApiClient(baseUrl: string): ApiClient {
  const base = baseUrl.replace(/\/+$/, '')

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response
    try {
      response = await fetch(`${base}${path}`, {
        ...init,
        headers: { Accept: 'application/json', ...init.headers },
      })
    } catch (err) {
      // Let callers distinguish deliberate cancellation from a network failure.
      if (err instanceof DOMException && err.name === 'AbortError') throw err
      throw new ApiRequestError(
        'Could not reach the planning service. Check your connection and try again.',
        'network_error',
        0,
      )
    }

    const body: unknown = await response.json().catch(() => null)

    if (!response.ok) {
      if (isApiError(body)) {
        throw new ApiRequestError(body.error, body.code, response.status, body.details)
      }
      throw new ApiRequestError(
        FALLBACK_MESSAGES[response.status] ?? `Unexpected server error (HTTP ${response.status}).`,
        response.status >= 500 ? 'server_error' : 'http_error',
        response.status,
      )
    }
    if (body === null) {
      throw new ApiRequestError('The server returned an unreadable response.', 'bad_response', response.status)
    }
    return body as T
  }

  return {
    planTrip: (payload, signal) =>
      request<PlanResponse>('/api/trips/plan/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal,
      }),
    geocode: (query, signal) =>
      request<GeocodeResponse>(`/api/geocode/?${new URLSearchParams({ q: query })}`, { signal }),
    reverse: (lat, lon, signal) =>
      request<ReverseGeocodeResponse>(
        `/api/reverse/?${new URLSearchParams({ lat: lat.toFixed(5), lon: lon.toFixed(5) })}`,
        { signal },
      ),
  }
}

export const api: ApiClient = createApiClient(import.meta.env.VITE_API_BASE_URL ?? '')

/** Friendly, action-oriented copy for an error, keyed by ApiError.code. */
export function describeError(error: unknown): { title: string; message: string } {
  if (error instanceof ApiRequestError) {
    switch (error.code) {
      case 'validation_error':
        return { title: 'Check the trip details', message: error.message }
      case 'geocode_failed':
        return {
          title: "We couldn't find that place",
          message: `${error.message} Or pick one of the suggestions as you type.`,
        }
      case 'route_not_found':
        return {
          title: 'No drivable route',
          message: `${error.message} Make sure all three locations are reachable by road in the US or Canada.`,
        }
      case 'upstream_unavailable':
        return {
          title: 'Routing service is busy',
          message: 'The free routing service did not respond. This is usually temporary; try again in a few seconds.',
        }
      case 'rate_limited':
        return {
          title: 'Too many plans in a short time',
          message: `${error.message} Planning is limited per network to keep the free routing services available.`,
        }
      case 'network_error':
        return { title: 'You appear to be offline', message: error.message }
      default:
        return { title: 'Something went wrong', message: error.message }
    }
  }
  return { title: 'Something went wrong', message: 'An unexpected error occurred. Please try again.' }
}
