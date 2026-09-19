import type { LogHeaderDetails } from '../../types/api'
import { Field } from '../ui'

const FIELDS: Array<{ key: keyof LogHeaderDetails; label: string; placeholder: string; wide?: boolean }> = [
  { key: 'driver_name', label: 'Driver', placeholder: 'Full name' },
  { key: 'co_driver', label: 'Co-driver', placeholder: 'N/A' },
  { key: 'carrier_name', label: 'Carrier', placeholder: 'Name of carrier', wide: true },
  { key: 'main_office', label: 'Main office address', placeholder: 'Street, City, ST', wide: true },
  { key: 'home_terminal', label: 'Home terminal address', placeholder: 'Street, City, ST', wide: true },
  { key: 'truck_number', label: 'Truck / tractor #', placeholder: 'e.g. T-2471' },
  { key: 'trailer_number', label: 'Trailer #', placeholder: 'e.g. TR-5318' },
  { key: 'shipping_doc', label: 'Shipping doc / shipper & commodity', placeholder: 'BOL or manifest #', wide: true },
]

interface LogHeaderFieldsProps {
  value: LogHeaderDetails
  onChange: <K extends keyof LogHeaderDetails>(key: K, value: LogHeaderDetails[K]) => void
}

export function LogHeaderFields({ value, onChange }: LogHeaderFieldsProps) {
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-3">
      {FIELDS.map((f) => (
        <Field
          key={f.key}
          label={f.label}
          placeholder={f.placeholder}
          value={value[f.key]}
          onChange={(e) => onChange(f.key, e.target.value)}
          className={f.wide ? 'col-span-2' : 'col-span-2 min-[400px]:col-span-1'}
          autoComplete="off"
        />
      ))}
    </div>
  )
}
