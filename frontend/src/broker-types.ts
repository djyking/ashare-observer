export interface BrokerField {key: string; label: string; secret: boolean; masked?: boolean; required: boolean; placeholder?: string; max_length?: number}
export interface BrokerDriver {id: string; name: string; description: string; available: boolean; environment: 'paper' | 'live'; fields: BrokerField[]}
export interface BrokerConnection {
  drivers: BrokerDriver[];
  profile: {driver: string; fields: Record<string, string>; masked_fields: Record<string, string>; saved_fields: string[]; secret_fields_ready: string[]; memory_only_fields?: string[]};
  state: {status: 'disconnected' | 'connecting' | 'connected' | 'error'; provider_id: string | null; message: string; last_checked_at: string | null};
  secrets_persisted: boolean; read_only: boolean;
}
export interface BrokerProvider {
  id: string; name: string; environment: 'paper' | 'live'; connected: boolean;
  capabilities: Record<'account' | 'positions' | 'orders' | 'trades' | 'place_order' | 'cancel_order', boolean>; message: string;
}
export interface BrokerCatalog {providers: BrokerProvider[]; live_enabled: boolean}
export type BrokerRecord = Record<string, string | number | boolean | null>;
export type BrokerQuery = 'account' | 'positions' | 'orders' | 'trades';
