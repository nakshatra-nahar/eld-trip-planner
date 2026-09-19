// One FMCSA-style "Driver's Daily Log" page, drawn as a self-contained SVG.
// All styling is inline SVG attributes (no CSS classes) so the exact same markup
// can be serialized for SVG/PNG download and printed without app styles.

import type { Ref } from 'react'
import { DUTY_HEX } from '../../lib/duty'
import { formatHoursClock, formatMinutesClock, placeLabel } from '../../lib/format'
import type { DailyLog, DutyStatus, LogHeaderDetails } from '../../types/api'
import {
  GRID,
  GRID_BOTTOM,
  GRID_TOP,
  PX_PER_HOUR,
  REMARKS,
  SHEET,
  STATUS_ORDER,
  bracketPath,
  buildDutyPath,
  restartState,
  splitShippingDoc,
  layoutRemarks,
  leaderPath,
  minutesByStatus,
  recapValues,
  roundedMinutesByStatus,
  splitDate,
  statusRowTop,
  statusToRowY,
  truncate,
} from './geometry'

export interface LogSheetProps {
  log: DailyLog
  header: LogHeaderDetails
  dayCount: number
  tripLabel?: string
  /** Printed under REMARKS, e.g. the two-duty-period driving note (see lib/dutyPeriods). */
  note?: string | null
  /** Home-terminal time zone the grid is drawn in, e.g. "CDT"; printed with the time-standard line. */
  tzAbbr?: string
  /** React 19 ref-as-prop: the root <svg>, used for SVG/PNG export. */
  ref?: Ref<SVGSVGElement>
  className?: string
  /**
   * Screen only: wash each grid row in its duty-status colour so the sheet reads with the
   * rest of the app. Marked `data-screen-only`, so print and SVG/PNG exports stay ink-on-paper.
   */
  tint?: boolean
}

// ---------- Visual tokens (inline so exports are self-contained) ----------

const PAPER = '#fffefa'
const PAPER_EDGE = '#d9d5c7'
const LINE = '#1c1c1e'
const FAINT = '#5f5f66'
const INK = '#1b3a8c'

const FORM_FONT = "'Helvetica Neue', Helvetica, Arial, sans-serif"
const GOV_FONT = "'Times New Roman', Times, Georgia, serif"
// Same family as the app's mono type; exporters.ts embeds it so downloads render identically.
export const INK_FONT = "'Geist Mono', 'SFMono-Regular', Menlo, Consolas, monospace"

const REMARK_FONT_SIZE = 10.5
const REMARK_ANGLE = 45 // clockwise: labels descend to the right, as on FMCSA p.18-19

const ROW_LABELS: Record<DutyStatus, [string, string?]> = {
  OFF: ['1. Off Duty'],
  SB: ['2. Sleeper', 'Berth'],
  D: ['3. Driving'],
  ON: ['4. On Duty', '(not driving)'],
}

const HOURS = Array.from({ length: 25 }, (_, h) => h)
const QUARTERS = Array.from({ length: 24 * 4 }, (_, q) => q).filter((q) => q % 4 !== 0)

function hourLabel(h: number): string {
  if (h === 0 || h === 24) return 'Mid-night'
  if (h === 12) return 'Noon'
  return String(h % 12)
}

// ---------- Small form primitives ----------

interface FieldProps {
  x1: number
  x2: number
  y: number // baseline of the rule
  label: string
  value?: string
  size?: number
  font?: string
  align?: 'start' | 'middle'
  maxChars?: number
}

/** A rule with a small caps caption under it and an ink value written on it. */
function Field({ x1, x2, y, label, value, size: baseSize = 15, font = INK_FONT, align = 'middle', maxChars }: FieldProps) {
  // Long values (e.g. full addresses) shrink a little to fit the rule before they are truncated.
  const room = x2 - x1 - 8
  const size = maxChars ? baseSize : Math.max(Math.min(baseSize, 9.5), Math.min(baseSize, room / (Math.max(1, value?.length ?? 0) * 0.6)))
  const max = maxChars ?? Math.floor(room / (size * 0.6))
  return (
    <g>
      <line x1={x1} x2={x2} y1={y} y2={y} stroke={LINE} strokeWidth={0.9} />
      <text
        x={(x1 + x2) / 2}
        y={y + 10.5}
        textAnchor="middle"
        fontFamily={FORM_FONT}
        fontSize={7.5}
        fontWeight={700}
        fill={LINE}
        letterSpacing={0.3}
      >
        {label}
      </text>
      {value ? (
        <text
          x={align === 'middle' ? (x1 + x2) / 2 : x1 + 6}
          y={y - 5}
          textAnchor={align}
          fontFamily={font}
          fontSize={size}
          fontWeight={500}
          fill={INK}
        >
          {truncate(value, max)}
        </text>
      ) : null}
    </g>
  )
}

/** Inline label followed by a rule, e.g. "From: ________". */
function InlineField({ x1, x2, y, label, value }: { x1: number; x2: number; y: number; label: string; value: string }) {
  const lineStart = x1 + label.length * 7.2 + 8
  return (
    <g>
      <text x={x1} y={y - 3} fontFamily={FORM_FONT} fontSize={12} fontWeight={700} fill={LINE}>
        {label}
      </text>
      <line x1={lineStart} x2={x2} y1={y} y2={y} stroke={LINE} strokeWidth={0.9} />
      <text x={lineStart + 6} y={y - 5} fontFamily={INK_FONT} fontSize={14} fontWeight={500} fill={INK}>
        {truncate(value, Math.floor((x2 - lineStart - 10) / (14 * 0.6)))}
      </text>
    </g>
  )
}

/** Hour lines plus :15/:30/:45 ticks hanging from `top` (the blank-form ruler). */
function Ruler({ top, bottom }: { top: number; bottom: number }) {
  const h = bottom - top
  return (
    <g stroke={LINE}>
      {HOURS.map((hr) => (
        <line
          key={`h${hr}`}
          x1={GRID.left + hr * PX_PER_HOUR}
          x2={GRID.left + hr * PX_PER_HOUR}
          y1={top}
          y2={bottom}
          strokeWidth={hr % 12 === 0 ? 1.3 : 0.8}
        />
      ))}
      {QUARTERS.map((q) => {
        const x = GRID.left + (q / 4) * PX_PER_HOUR
        const len = q % 2 === 0 ? h * 0.42 : h * 0.22
        return <line key={`q${q}`} x1={x} x2={x} y1={top} y2={top + len} strokeWidth={0.6} />
      })}
    </g>
  )
}

// ---------- The sheet ----------

export function LogSheet({ log, header, dayCount, tripLabel, note, tzAbbr, ref, className, tint = false }: LogSheetProps) {
  const { month, day, year } = splitDate(log.date)
  // Row totals in whole minutes straight from the drawn segments, so what is printed is
  // exactly what is drawn and the rows always add up to 24:00.
  const rowMinutes = roundedMinutesByStatus(minutesByStatus(log.segments))
  const grandTotal = STATUS_ORDER.reduce((a, s) => a + rowMinutes[s], 0)
  const recap = recapValues(log)
  const dutyPath = buildDutyPath(log.segments)
  const remarks = layoutRemarks(log.remarks, { fontSize: REMARK_FONT_SIZE, angle: REMARK_ANGLE })
  const restart = restartState(log.remarks, log.cycle_hours_used)
  const miles = Math.round(log.total_miles).toLocaleString('en-US')
  const vehicles = [header.truck_number, header.trailer_number].map((v) => v.trim()).filter(Boolean).join(', ')
  const shipping = splitShippingDoc(header.shipping_doc)

  const title = `Driver's daily log, ${log.date}, day ${log.day_number} of ${dayCount}`

  return (
    <svg
      ref={ref}
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${SHEET.width} ${SHEET.height}`}
      width="100%"
      role="img"
      aria-label={title}
      style={{ display: 'block', height: 'auto' }}
      shapeRendering="geometricPrecision"
      textRendering="geometricPrecision"
    >
      <title>{title}</title>

      {/* Paper */}
      <rect x={0} y={0} width={SHEET.width} height={SHEET.height} fill={PAPER} />
      <rect x={6.5} y={6.5} width={SHEET.width - 13} height={SHEET.height - 13} fill="none" stroke={PAPER_EDGE} strokeWidth={1} rx={3} />

      {/* ---------- Title block ---------- */}
      <g>
        <rect x={40} y={17} width={92} height={21} rx={3} fill="none" stroke={INK} strokeWidth={1.2} />
        <text x={86} y={31.5} textAnchor="middle" fontFamily={INK_FONT} fontSize={11} fontWeight={700} fill={INK} letterSpacing={0.6}>
          {`DAY ${log.day_number} OF ${dayCount}`}
        </text>
        {tripLabel ? (
          <text x={142} y={31.5} fontFamily={FORM_FONT} fontSize={9.5} fill={FAINT}>
            {truncate(tripLabel, 46)}
          </text>
        ) : null}
        <text x={40} y={60} fontFamily={GOV_FONT} fontSize={11.5} fill={LINE} letterSpacing={0.4}>
          U.S. DEPARTMENT OF TRANSPORTATION
        </text>

        <text x={SHEET.width / 2} y={38} textAnchor="middle" fontFamily={FORM_FONT} fontSize={19} fontWeight={800} fill={LINE} letterSpacing={0.5}>
          DRIVER&#8217;S DAILY LOG
        </text>
        <text x={SHEET.width / 2} y={53} textAnchor="middle" fontFamily={FORM_FONT} fontSize={8.5} fontWeight={700} fill={LINE} letterSpacing={0.4}>
          (ONE CALENDAR DAY — 24 HOURS)
        </text>

        <text x={GRID.totalsRight} y={30} textAnchor="end" fontFamily={FORM_FONT} fontSize={8} fontWeight={700} fill={LINE}>
          ORIGINAL — Submit to carrier within 13 days
        </text>
        <text x={GRID.totalsRight} y={42} textAnchor="end" fontFamily={FORM_FONT} fontSize={8} fontWeight={700} fill={LINE}>
          DUPLICATE — Driver retains possession for eight days
        </text>

        {/* Date, mileage, vehicles */}
        <Field x1={40} x2={88} y={100} label="(MONTH)" value={month} size={20} />
        <text x={94} y={96} textAnchor="middle" fontFamily={FORM_FONT} fontSize={18} fill={LINE}>/</text>
        <Field x1={100} x2={148} y={100} label="(DAY)" value={day} size={20} />
        <text x={154} y={96} textAnchor="middle" fontFamily={FORM_FONT} fontSize={18} fill={LINE}>/</text>
        <Field x1={160} x2={236} y={100} label="(YEAR)" value={year} size={20} />
        <Field x1={266} x2={436} y={100} label="(TOTAL MILES DRIVING TODAY)" value={miles} size={20} />
        <Field x1={456} x2={616} y={100} label="(TOTAL MILEAGE TODAY)" value={miles} size={20} />
        <Field
          x1={646}
          x2={GRID.totalsRight}
          y={100}
          label="(TRUCK/TRACTOR AND TRAILER NUMBERS OR LICENSE PLATE(S)/STATE — SHOW EACH UNIT)"
          value={vehicles}
          size={18}
        />

        {/* From / To */}
        <InlineField x1={40} x2={520} y={146} label="From:" value={placeLabel(log.from_location)} />
        <InlineField x1={560} x2={GRID.totalsRight} y={146} label="To:" value={placeLabel(log.to_location)} />

        {/* Carrier and signature */}
        <text x={560} y={170} fontFamily={FORM_FONT} fontSize={7.5} fill={LINE}>
          I certify that these entries are true and correct
        </text>
        <Field x1={40} x2={520} y={196} label="(NAME OF CARRIER OR CARRIERS)" value={header.carrier_name} size={16} />
        {/* Signed in the driver's name, as on the FMCSA sample log (blank when the name is cleared). */}
        <Field x1={560} x2={830} y={196} label="(DRIVER'S SIGNATURE IN FULL)" />
        {header.driver_name.trim() ? (
          <text
            x={572}
            y={189}
            fontFamily={GOV_FONT}
            fontSize={21}
            fontStyle="italic"
            fill={INK}
            transform="rotate(-3 572 189)"
          >
            {truncate(header.driver_name.trim(), 26)}
          </text>
        ) : null}
        <Field x1={846} x2={GRID.totalsRight} y={196} label="(DRIVER NAME, PRINTED)" value={header.driver_name} size={14} />

        {/* Addresses and co-driver */}
        <Field x1={40} x2={276} y={240} label="(MAIN OFFICE ADDRESS)" value={header.main_office} size={12.5} />
        <Field x1={292} x2={520} y={240} label="(HOME TERMINAL ADDRESS)" value={header.home_terminal} size={12.5} />
        <Field x1={560} x2={GRID.totalsRight} y={240} label="(NAME OF CO-DRIVER)" value={header.co_driver} size={14} />
      </g>

      {/* ---------- 24-hour grid ---------- */}
      <g>
        {/* Black hour bar */}
        <rect x={GRID.left - 34} y={GRID.barTop} width={GRID.totalsRight - GRID.left + 34} height={GRID.barHeight} fill={LINE} />
        {HOURS.map((h) => {
          const x = GRID.left + h * PX_PER_HOUR
          const label = hourLabel(h)
          if (label === 'Mid-night') {
            return (
              <text key={h} x={x} textAnchor="middle" fontFamily={FORM_FONT} fontSize={7.5} fontWeight={700} fill="#fff">
                <tspan x={x} y={GRID.barTop + 10}>Mid-</tspan>
                <tspan x={x} y={GRID.barTop + 19}>night</tspan>
              </text>
            )
          }
          return (
            <text key={h} x={x} y={GRID.barTop + 16} textAnchor="middle" fontFamily={FORM_FONT} fontSize={label === 'Noon' ? 8.5 : 10} fontWeight={700} fill="#fff">
              {label}
            </text>
          )
        })}
        <text textAnchor="middle" fontFamily={FORM_FONT} fontSize={7.5} fontWeight={700} fill="#b9b9c0">
          <tspan x={(GRID.totalsLeft + GRID.totalsRight) / 2 + 6} y={GRID.barTop + 10}>Total</tspan>
          <tspan x={(GRID.totalsLeft + GRID.totalsRight) / 2 + 6} y={GRID.barTop + 19}>Hours</tspan>
        </text>

        {tint ? (
          <g data-screen-only>
            {STATUS_ORDER.map((status) => (
              <rect
                key={status}
                x={GRID.left}
                y={statusRowTop(status)}
                width={GRID.right - GRID.left}
                height={GRID.rowHeight}
                fill={DUTY_HEX[status]}
                opacity={0.07}
              />
            ))}
          </g>
        ) : null}

        {/* Rows */}
        {STATUS_ORDER.map((status) => {
          const top = statusRowTop(status)
          const [l1, l2] = ROW_LABELS[status]
          const cy = statusToRowY(status)
          return (
            <g key={status}>
              <Ruler top={top} bottom={top + GRID.rowHeight} />
              <text x={GRID.labelX} fontFamily={FORM_FONT} fontSize={10.5} fontWeight={700} fill={LINE}>
                <tspan x={GRID.labelX} y={l2 ? cy - 2 : cy + 4}>{l1}</tspan>
                {l2 ? <tspan x={GRID.labelX + 14} y={cy + 10} fontSize={9.5} fontWeight={600}>{l2}</tspan> : null}
              </text>
              {/* Row total, written on its own rule like the blank form */}
              <line x1={GRID.totalsLeft} x2={GRID.totalsRight} y1={top + GRID.rowHeight - 5} y2={top + GRID.rowHeight - 5} stroke={LINE} strokeWidth={0.9} />
              <text x={GRID.totalsRight - 2} y={top + GRID.rowHeight - 10} textAnchor="end" fontFamily={INK_FONT} fontSize={15} fontWeight={600} fill={INK}>
                {formatMinutesClock(rowMinutes[status])}
              </text>
            </g>
          )
        })}
        {STATUS_ORDER.slice(1).map((s) => (
          <line key={s} x1={GRID.left} x2={GRID.right} y1={statusRowTop(s)} y2={statusRowTop(s)} stroke={LINE} strokeWidth={1} />
        ))}
        <rect x={GRID.left} y={GRID_TOP} width={GRID.right - GRID.left} height={GRID_BOTTOM - GRID_TOP} fill="none" stroke={LINE} strokeWidth={1.4} />

        {/* The duty-status line */}
        <path d={dutyPath} fill="none" stroke={INK} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      </g>

      {/* ---------- Remarks ---------- */}
      <g>
        {HOURS.map((h) => (
          <text
            key={h}
            x={GRID.left + h * PX_PER_HOUR}
            y={REMARKS.labelY}
            textAnchor="middle"
            fontFamily={FORM_FONT}
            fontSize={7}
            fill={FAINT}
          >
            {h === 0 || h === 24 ? 'Midnight' : h === 12 ? 'Noon' : h % 12}
          </text>
        ))}
        <Ruler top={REMARKS.rulerTop} bottom={REMARKS.rulerBottom} />
        <line x1={GRID.left} x2={GRID.right} y1={REMARKS.rulerTop} y2={REMARKS.rulerTop} stroke={LINE} strokeWidth={1.2} />
        <line x1={GRID.left} x2={GRID.right} y1={REMARKS.rulerBottom} y2={REMARKS.rulerBottom} stroke={LINE} strokeWidth={1.2} />
        <text x={GRID.labelX} y={REMARKS.rulerBottom - 3} fontFamily={FORM_FONT} fontSize={12} fontWeight={800} fill={LINE} letterSpacing={0.8}>
          REMARKS
        </text>

        {/* Grand total, double underlined */}
        <text x={GRID.totalsRight - 2} y={REMARKS.rulerBottom - 3} textAnchor="end" fontFamily={INK_FONT} fontSize={16} fontWeight={700} fill={INK}>
          {`=${formatMinutesClock(grandTotal)}`}
        </text>
        <line x1={GRID.totalsLeft} x2={GRID.totalsRight} y1={REMARKS.rulerBottom + 2} y2={REMARKS.rulerBottom + 2} stroke={LINE} strokeWidth={0.9} />
        <line x1={GRID.totalsLeft} x2={GRID.totalsRight} y1={REMARKS.rulerBottom + 5} y2={REMARKS.rulerBottom + 5} stroke={LINE} strokeWidth={0.9} />

        {/* Blank-form style frame for the remarks area */}
        <path d={`M${GRID.left - 10} ${REMARKS.rulerBottom + 6} V${REMARKS.bottom + 6}`} stroke={LINE} strokeWidth={2} fill="none" />

        {/* Brackets and leaders first, then every label on top with a paper halo, so no
            line drawn later can cross an earlier label. */}
        {log.remarks.map((rm, i) => (
          <path
            key={`b${rm.start_minute}-${i}`}
            d={bracketPath(rm.start_minute, rm.end_minute)}
            fill="none"
            stroke={INK}
            strokeWidth={1.8}
            strokeLinejoin="round"
          />
        ))}
        {remarks.map((rm, i) =>
          rm.displaced ? (
            <path
              key={`l${i}`}
              d={leaderPath(rm)}
              fill="none"
              stroke={INK}
              strokeWidth={0.7}
              strokeDasharray="2 2"
              opacity={0.7}
            />
          ) : null,
        )}
        {remarks.map((rm, i) => (
          <text
            key={`t${i}`}
            x={rm.anchorX}
            y={rm.anchorY}
            transform={`rotate(${REMARK_ANGLE} ${rm.anchorX} ${rm.anchorY})`}
            fontFamily={INK_FONT}
            fontSize={rm.fontSize}
            fontWeight={500}
            fill={INK}
            stroke={PAPER}
            strokeWidth={3}
            strokeLinejoin="round"
            paintOrder="stroke"
          >
            <title>{rm.text}</title>
            {rm.lines.map((line, k) => (
              <tspan key={k} x={rm.anchorX} dy={k === 0 ? 0 : rm.lineHeight}>
                {line}
              </tspan>
            ))}
          </text>
        ))}

        {/* Two duty periods on one sheet: say why Driving may exceed 11:00 (left of the remarks). */}
        {note ? <NoteBlock text={note} /> : null}
      </g>

      {/* ---------- Shipping documents ---------- */}
      <g>
        <line x1={GRID.labelX} x2={GRID.totalsRight} y1={REMARKS.bottom + 8} y2={REMARKS.bottom + 8} stroke={LINE} strokeWidth={1} />
        <text x={40} y={690} fontFamily={FORM_FONT} fontSize={11} fontWeight={800} fill={LINE}>
          Shipping Documents:
        </text>
        <Field x1={180} x2={470} y={710} label="DVL OR MANIFEST NO." value={shipping.manifest} size={14} />
        <text x={490} y={706} fontFamily={FORM_FONT} fontSize={10} fontStyle="italic" fill={FAINT}>or</text>
        <Field x1={512} x2={GRID.totalsRight} y={710} label="SHIPPER & COMMODITY" value={shipping.shipper} size={14} />
        <text x={SHEET.width / 2} y={738} textAnchor="middle" fontFamily={FORM_FONT} fontSize={8.5} fontWeight={700} fill={LINE}>
          Enter name of place you reported and where released from work and when and where each change of duty occurred. Use time standard of home terminal
          {tzAbbr ? (
            <tspan fill={INK} fontFamily={INK_FONT} fontSize={9.5}>{` (times shown: ${tzAbbr})`}</tspan>
          ) : null}
          .
        </text>
      </g>

      {/* ---------- Recap: 70 hour / 8 day ---------- */}
      <g fontFamily={FORM_FONT} fill={LINE}>
        <line x1={GRID.labelX} x2={GRID.totalsRight} y1={748} y2={748} stroke={LINE} strokeWidth={1.6} />
        <text x={40} y={766} fontSize={11} fontWeight={800}>Recap:</text>
        <text x={40} y={779} fontSize={9} fontWeight={600}>Complete at end of day</text>

        <text fontSize={9} fontWeight={600}>
          <tspan x={170} y={766}>On duty hours today,</tspan>
          <tspan x={170} y={778}>Total lines 3 &amp; 4</tspan>
        </text>
        <RecapValue x={170} value={formatMinutesClock(recap.onDutyTodayMinutes)} />

        <text fontSize={10.5} fontWeight={800}>
          <tspan x={318} y={766}>70 Hour /</tspan>
          <tspan x={318} y={779}>8 Day Drivers</tspan>
        </text>

        <RecapColumn x={410} letter="A." lines={['Total hours on duty last 7', 'days including today']} value={formatHoursClock(recap.a)} />
        <RecapColumn x={570} letter="B." lines={['Total hours available', 'tomorrow 70 hr. minus A*']} value={formatHoursClock(recap.b)} />
        <RecapColumn x={730} letter="C." lines={['Total hours on duty last 8', 'days including today']} value={formatHoursClock(recap.c)} />

        <text fontSize={7} fill={FAINT}>
          <tspan x={40} y={830}>
            *34 consecutive hours off duty resets to 70 available. A and C show every hour used this cycle,
            including hours carried in (they have no per-day breakdown), so they may be higher than the
          </tspan>
          <tspan x={40} y={839}>
            true 7- and 8-day sums: a conservative figure.
          </tspan>
        </text>
        {restart ? (
          <g>
            <rect x={900} y={778} width={160} height={42} rx={4} fill="none" stroke={INK} strokeWidth={1.4} />
            <text textAnchor="middle" fontFamily={INK_FONT} fontSize={10.5} fontWeight={700} fill={INK}>
              <tspan x={980} y={795}>34-hr restart</tspan>
              <tspan x={980} y={810}>{restart === 'completed' ? 'taken' : 'in progress'}</tspan>
            </text>
          </g>
        ) : null}
      </g>
    </svg>
  )
}

/** One lettered recap column: caption (two lines) over a written value. */
function RecapColumn({ x, letter, lines, value }: { x: number; letter: string; lines: [string, string]; value: string }) {
  return (
    <g>
      <text fontSize={9} fontWeight={600}>
        <tspan x={x} y={766} fontSize={11} fontWeight={800}>
          {letter}
        </tspan>
        <tspan x={x + 16} y={766}>{lines[0]}</tspan>
        <tspan x={x + 16} y={778}>{lines[1]}</tspan>
      </text>
      <RecapValue x={x + 16} value={value} />
    </g>
  )
}

/** Small printed note in the empty column left of the remarks, wrapped by words. */
function NoteBlock({ text }: { text: string }) {
  const lines = wrapWords(text, 24)
  return (
    <g>
      <rect x={GRID.labelX - 4} y={REMARKS.rulerBottom + 14} width={112} height={lines.length * 11 + 10} rx={3} fill="none" stroke={INK} strokeWidth={0.9} />
      <text fontFamily={FORM_FONT} fontSize={8.5} fontWeight={600} fill={INK}>
        {lines.map((line, i) => (
          <tspan key={i} x={GRID.labelX + 2} y={REMARKS.rulerBottom + 27 + i * 11}>
            {line}
          </tspan>
        ))}
      </text>
    </g>
  )
}

function wrapWords(text: string, maxChars: number): string[] {
  const lines: string[] = []
  for (const word of text.split(/\s+/)) {
    const last = lines[lines.length - 1]
    if (last !== undefined && `${last} ${word}`.length <= maxChars) lines[lines.length - 1] = `${last} ${word}`
    else lines.push(word)
  }
  return lines
}

function RecapValue({ x, value }: { x: number; value: string }) {
  return (
    <g>
      <line x1={x} x2={x + 120} y1={818} y2={818} stroke={LINE} strokeWidth={0.9} />
      <text x={x + 6} y={812} fontFamily={INK_FONT} fontSize={20} fontWeight={600} fill={INK}>
        {value}
      </text>
    </g>
  )
}

export default LogSheet
