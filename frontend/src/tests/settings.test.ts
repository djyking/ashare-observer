import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import Settings from '../components/Settings.vue'
import { snapshot } from './fixtures'

describe('settings hydration and edits', () => {
  it('disables every input until the first settings snapshot, then hydrates it', async () => {
    const mutate = vi.fn().mockResolvedValue(true)
    const wrapper = mount(Settings, { props: { settings: null, busy: false, mutate } })
    expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
    await wrapper.get('form').trigger('submit'); expect(mutate).not.toHaveBeenCalled()
    await wrapper.setProps({ settings: snapshot().settings })
    expect(wrapper.get('fieldset').attributes('disabled')).toBeUndefined()
    expect((wrapper.get('#settings-watchlist').element as HTMLTextAreaElement).value).toBe('600036')
    expect((wrapper.get('#settings-interval').element as HTMLInputElement).value).toBe('300')
  })
  it('preserves unsaved form edits across background snapshots and failed saves', async () => {
    const mutate = vi.fn().mockResolvedValue(false)
    const wrapper = mount(Settings, { props: { settings: snapshot().settings, busy: false, mutate } })
    await wrapper.get('#settings-watchlist').setValue('000333,600036')
    await wrapper.setProps({ settings: { ...snapshot().settings, refresh_seconds: 600 } })
    expect((wrapper.get('#settings-watchlist').element as HTMLTextAreaElement).value).toBe('000333,600036')
    expect((wrapper.get('#settings-interval').element as HTMLInputElement).value).toBe('300')
    await wrapper.get('form').trigger('submit')
    expect(mutate).toHaveBeenCalledWith('/api/settings', expect.objectContaining({ watchlist: ['000333', '600036'] }), expect.any(String))
    expect(wrapper.text()).toContain('有未保存的修改')
  })
  it('rejects invalid intervals before posting and refreshes unedited settings', async () => {
    const mutate = vi.fn()
    const wrapper = mount(Settings, { props: { settings: snapshot().settings, busy: false, mutate } })
    await wrapper.setProps({ settings: { ...snapshot().settings, refresh_seconds: 600 } })
    expect((wrapper.get('#settings-interval').element as HTMLInputElement).value).toBe('600')
    await wrapper.get('#settings-interval').setValue('60'); await wrapper.get('form').trigger('submit')
    expect(mutate).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('300–86400')
  })
  it('keeps submitted settings if POST succeeded but the following snapshot fetch failed', async () => {
    const mutate = vi.fn().mockResolvedValue(true)
    const wrapper = mount(Settings, { props: { settings: snapshot().settings, busy: false, mutate } })
    await wrapper.get('#settings-watchlist').setValue('000333,600036')
    await wrapper.get('#settings-interval').setValue('600')
    await wrapper.get('form').trigger('submit')
    expect((wrapper.get('#settings-watchlist').element as HTMLTextAreaElement).value).toBe('000333,600036')
    expect((wrapper.get('#settings-interval').element as HTMLInputElement).value).toBe('600')
    expect(wrapper.text()).not.toContain('有未保存的修改')
    await wrapper.setProps({ settings: { ...snapshot().settings, watchlist: ['000333', '600036'], refresh_seconds: 600 } })
    expect((wrapper.get('#settings-watchlist').element as HTMLTextAreaElement).value).toBe('000333, 600036')
  })
})
