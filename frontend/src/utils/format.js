// 金额显示：传入字符串或数字，统一补两位小数
export const yuan = (v) => {
  const n = Number(v || 0)
  return (Number.isInteger(n) ? n.toFixed(2) : n.toFixed(2))
}
