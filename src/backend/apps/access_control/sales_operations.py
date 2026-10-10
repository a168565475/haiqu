"""Independent sales workflow grants; legacy grants remain explicit exceptions."""
SALES_OPERATIONS = (
    ("submit_inquiry", "提交询盘", "inquiries", "inquiries.change_inquiry"),
    ("start_inquiry", "开始处理询盘", "inquiries", "inquiries.change_inquiry"),
    ("respond_inquiry", "响应询盘", "inquiries", "inquiries.change_inquiry"),
    ("confirmrequirements_inquiry", "确认询盘需求", "inquiries", "inquiries.change_inquiry"),
    ("syncquotation_inquiry", "同步询盘报价", "inquiries", "inquiries.change_inquiry"),
    ("markquoted_inquiry", "登记询盘已报价", "inquiries", "inquiries.change_inquiry"),
    ("followup_inquiry", "跟进询盘", "inquiries", "inquiries.change_inquiry"),
    ("marklost_inquiry", "登记询盘丢失", "inquiries", "inquiries.change_inquiry"),
    ("close_inquiry", "关闭询盘", "inquiries", "inquiries.change_inquiry"),
    ("cancel_inquiry", "取消询盘", "inquiries", "inquiries.change_inquiry"),
    ("markinvalid_inquiry", "标记无效询盘", "inquiries", "inquiries.change_inquiry"),
    ("lose_quotation", "登记报价丢失", "quotations", "quotations.change_quotation"),
    ("cancel_quotation", "取消报价", "quotations", "quotations.change_quotation"),
    ("lock_quotationversion", "锁定报价版本", "quotations", "quotations.change_quotationversion"),
    ("submit_quotationversion", "提交报价审批", "quotations", "quotations.change_quotationversion"),
    ("void_quotationversion", "作废报价版本", "quotations", "quotations.change_quotationversion"),
    ("confirmedchange_salesorder", "变更已确认订单", "sales_orders", "sales_orders.change_salesorder"),
    ("collaborate_salesorder", "登记订单协同", "sales_orders", "sales_orders.change_salesorder"),
    ("cancelbatch_salesorder", "取消订单交付批次", "sales_orders", "sales_orders.change_salesorder"),
    ("archive_customeraccount", "归档客户", "customers", "customers.change_customeraccount"),
    ("restore_customeraccount", "恢复客户", "customers", "customers.change_customeraccount"),
)
LEGACY_ACTION_PERMISSIONS = {f"access_control.{code}": old for code, _, _, old in SALES_OPERATIONS}
INQUIRY_ACTIONS = {
    "submit": "submit", "start": "start", "respond": "respond",
    "confirm_requirements": "confirmrequirements", "sync_quotation": "syncquotation",
    "mark_quoted": "markquoted", "follow_up": "followup", "mark_lost": "marklost",
    "close": "close", "cancel": "cancel", "mark_invalid": "markinvalid",
}
