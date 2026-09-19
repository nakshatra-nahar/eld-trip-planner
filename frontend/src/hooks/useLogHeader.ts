import { useCallback, useEffect, useState } from 'react'
import { readJson, writeJson } from '../lib/storage'
import type { LogHeaderDetails } from '../types/api'

const STORAGE_KEY = 'routelog.log-header.v1'

/** Sample values so a first-time visitor sees fully filled-out log sheets. Editable and cleared on demand. */
export const SAMPLE_LOG_HEADER: LogHeaderDetails = {
  driver_name: 'Alex Morgan',
  co_driver: 'N/A',
  carrier_name: 'Blue Ridge Freight LLC',
  main_office: '1200 Commerce Dr, Joliet, IL 60431',
  home_terminal: '1200 Commerce Dr, Joliet, IL 60431',
  truck_number: 'T-2471',
  trailer_number: 'TR-5318',
  shipping_doc: 'BOL 88412 · Acme Paper Co. / paper products',
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

/** Log-sheet header details, persisted in localStorage. */
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
