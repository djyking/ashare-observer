import { computed, ref, shallowRef } from 'vue'
import { latestRequest, request } from '../api'
import type { Mutate, Snapshot } from '../types'

export function usePlatform() {
  const snapshot = shallowRef<Snapshot | null>(null)
  const loading = ref(false), actionBusy = ref(false), connectionError = ref(''), feedback = ref(''), feedbackError = ref(false)
  const ready = computed(() => !!snapshot.value)
  const busy = computed(() => actionBusy.value || !!snapshot.value?.app.refreshing)
  const demoReady = computed(() => ready.value && !busy.value && snapshot.value?.app.mode === 'demo')
  const generation = latestRequest()
  let pending: Promise<void> | null = null
  let disposed = false

  async function load(force = false): Promise<void> {
    if (disposed) return
    if (pending && !force) return pending
    const id = generation.next()
    loading.value = true
    const job = (async () => {
      try {
        const data = await request<Snapshot>('/api/state')
        if (!generation.current(id)) return
        snapshot.value = data
        connectionError.value = ''
      } catch (error) {
        if (generation.current(id)) connectionError.value = error instanceof Error ? error.message : String(error)
      } finally {
        if (generation.current(id)) { loading.value = false; pending = null }
      }
    })()
    pending = job
    return job
  }

  const mutate: Mutate = async (path, body, message) => {
    if (disposed || !ready.value || busy.value) return false
    actionBusy.value = true
    // Discard in-flight snapshots begun before this mutation.
    generation.invalidate()
    feedback.value = ''
    let accepted = false
    try {
      await request(path, body, snapshot.value!.csrf_token)
      if (disposed) return false
      accepted = true
      feedback.value = message
      feedbackError.value = false
      await load(true)
    } catch (error) {
      if (disposed) return false
      feedback.value = error instanceof Error ? error.message : String(error)
      feedbackError.value = true
      await load(true)
    } finally { actionBusy.value = false }
    return accepted
  }
  function dispose() {
    disposed = true
    generation.invalidate()
    pending = null
    loading.value = false
    actionBusy.value = false
  }
  return { snapshot, ready, loading, busy, demoReady, actionBusy, connectionError, feedback, feedbackError, load, mutate, dispose }
}
