import { defineStore } from 'pinia'

type OperatorProfile = {
  name: string
  team: string
}

export const OPERATOR_PROFILES: OperatorProfile[] = [
  { name: '张工', team: '锅炉班' },
  { name: '李工', team: '电梯班' },
  { name: '王工', team: '起重班' },
  { name: '陈主管', team: '锅炉班' },
  { name: '赵值班', team: '运行一班' },
  { name: '外协人员', team: '外协班组' },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: OPERATOR_PROFILES[0].name,
    team: OPERATOR_PROFILES[0].team,
    shiftLabel: '白班 08:00-20:00',
    scope: '特种设备安全管理平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
  },
  actions: {
    setOperator(profile: OperatorProfile) {
      this.operator = profile.name
      this.team = profile.team
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
  },
})
