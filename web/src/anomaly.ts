// The anomaly view of a layer: the same layer, shown as the difference from its 1991-2020
// mean for the calendar month, on a diverging scale centred on zero.
import type { LayerMeta } from './manifest';

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December'];

export function monthName(date: string): string {
  return MONTHS[Number(date.slice(5, 7)) - 1]!;
}

/** Layer metadata for drawing the anomaly: its encoding, fixed display range and colours. */
export function anomalyView(meta: LayerMeta): LayerMeta {
  if (!meta.anomaly_encode || !meta.anomaly_display || !meta.anomaly_colour) {
    throw new Error(`${meta.title} has no anomaly`);
  }
  return {
    ...meta,
    title: `${meta.title}, anomaly`,
    encode: meta.anomaly_encode,
    display: meta.anomaly_display,
    log: false, // anomalies are linear in layer units, even for log layers
    centre: 0,
    colour: meta.anomaly_colour,
    hatch_zero: false,
  };
}

export function anomalyNote(period: string, date: string): string {
  return `Difference from the ${period.replace('-', '–')} ${monthName(date)} mean`;
}
