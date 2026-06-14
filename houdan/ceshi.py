"""探测 OrderLogisticsInformationRequest 和 AlipayMerchantOrderSyncModel 的字段，
确认 alipay_client.py 里给这些 model 设的属性名 SDK 都接受。
"""

print("== OrderLogisticsInformationRequest 字段 ==")
try:
    from alipay.aop.api.domain.OrderLogisticsInformationRequest import OrderLogisticsInformationRequest
    li = OrderLogisticsInformationRequest()
    fields = sorted(a for a in dir(li) if not a.startswith('_') and not callable(getattr(li, a, None)))
    for f in fields:
        print("  ", f)
except Exception as e:
    print("   import 失败:", e)

print()
print("== AlipayMerchantOrderSyncModel 字段 ==")
try:
    from alipay.aop.api.domain.AlipayMerchantOrderSyncModel import AlipayMerchantOrderSyncModel
    m = AlipayMerchantOrderSyncModel()
    fields = sorted(a for a in dir(m) if not a.startswith('_') and not callable(getattr(m, a, None)))
    for f in fields:
        print("  ", f)
except Exception as e:
    print("   import 失败:", e)

print()
print("== 对照检查 alipay_client.py 里使用的字段 ==")
checks_li = ['logistics_no', 'logistics_org_code', 'logistics_company_code',
             'delivery_type', 'delivery_time', 'consignee_name', 'consignee_phone']
checks_model = ['out_biz_no', 'order_type', 'biz_type', 'status', 'amount',
                'buyer_id', 'seller_id', 'ext_info', 'extend_info', 'logistics_info_list']
try:
    li = OrderLogisticsInformationRequest()
    print("  [logistics] 字段是否存在：")
    for f in checks_li:
        print(f"    {f}: {'✓' if hasattr(li, f) else '✗'}")
except Exception:
    pass
try:
    m = AlipayMerchantOrderSyncModel()
    print("  [model] 字段是否存在：")
    for f in checks_model:
        print(f"    {f}: {'✓' if hasattr(m, f) else '✗'}")
except Exception:
    pass
