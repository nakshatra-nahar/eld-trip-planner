import { useCallback, useEffect, useState } from 'react'
import { readJson, writeJson } from '../lib/storage'
import type { LogHeaderDetails } from '../types/api'

// v3: sheets start filled with the FMCSA guide's own sample identity (PDF p.19) so every
// log is complete out of the box; drivers edit or clear it under "Log sheet details".
const STORAGE_KEY = 'routelog.log-header.v3'

/** Example header modelled on the FMCSA "A Completed Log" sample (John E. Doe, Washington, D.C.). */
export const SAMPLE_LOG_HEADER: LogHeaderDetails = {
  driver_name: 'John E. Doe',
  co_driver: 'N/A',
  carrier_name: "John Doe's Transportation",
  main_office: 'Washington, D.C.',
  home_terminal: 'Washington, D.C.',
  truck_number: '123',
  trailer_number: '20544',
  shipping_doc: 'Pro No. 101601 · General freight',
}

export const EMPTY_LOG_HEADER: LogHeaderDetails = {
  driver_name: '',
  co_driver: '',
  carrier_name: '',
  main_office: '',
  home_terminal: '',
  truck_number: '',
  trailer_number: '',
  shipping_doc: '',
}

/**
 * Log-sheet header details, persisted in localStorage. Defaults to the FMCSA sample identity so
 * the sheets are fully filled out; the form labels these values as sample data.
 */
export function useLogHeader() {
  const [header, setHeader] = useState<LogHeaderDetails>(() => readJson(STORAGE_KEY, SAMPLE_LOG_HEADER))

  useEffect(() => {
    writeJson(STORAGE_KEY, header)
  }, [header])

  const update = useCallback(<K extends keyof LogHeaderDetails>(key: K, value: LogHeaderDetails[K]) => {
    setHeader((prev) => ({ ...prev, [key]: value }))
  }, [])

  return { header, setHeader, update }
}
