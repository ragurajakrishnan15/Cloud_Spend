view: budget_variance {
  sql_table_name: CLOUDSPEND_AI.REPORTING.VW_BUDGET_VARIANCE ;;

  dimension: pk {
    primary_key: yes
    hidden: yes
    sql: ${TABLE}.YEAR_MONTH || '|' || ${TABLE}.DEPARTMENT_NAME || '|' || ${TABLE}.SERVICE_NAME ;;
  }
  dimension_group: month {
    type: time
    timeframes: [month, quarter, year]
    datatype: date
    sql: ${TABLE}.MONTH_START ;;
  }
  dimension: department_name { type: string sql: ${TABLE}.DEPARTMENT_NAME ;; }
  dimension: service_name { type: string sql: ${TABLE}.SERVICE_NAME ;; }
  dimension: is_over_budget { type: yesno sql: ${TABLE}.IS_OVER_BUDGET ;; }

  measure: actual_cost { type: sum sql: ${TABLE}.ACTUAL_COST ;; value_format_name: usd_0 }
  measure: budget_amount { type: sum sql: ${TABLE}.BUDGET_AMOUNT ;; value_format_name: usd_0 }
  measure: variance_amount {
    type: number
    sql: ${actual_cost} - ${budget_amount} ;;
    value_format_name: usd_0
    description: "Actual - budget. Positive = over budget."
  }
  measure: variance_pct {
    type: number
    sql: ${variance_amount} / NULLIF(${budget_amount}, 0) ;;
    value_format_name: percent_1
    description: "Variance / budget, computed from summed amounts (NULL when the budget is zero)."
  }
  measure: over_budget_lines {
    type: count
    filters: [is_over_budget: "yes"]
    description: "Number of department x service x month lines over budget."
  }
}
