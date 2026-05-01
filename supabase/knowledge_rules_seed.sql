insert into public.knowledge_rules
(rule_key, layer, campaign_type, required_metrics, condition_logic, meaning_ar, recommended_action_ar, next_metric, enabled)
values
('anti_hallucination_no_website_funnel_for_messages','anti_hallucination','messages',array['messaging_conversations']::text[],'campaign_type == messages','حملات الرسائل لا تعني وجود صفحة هبوط أو سلة أو دفع.','لا تعرض website funnel إلا إذا أثبتت البيانات وجود outbound/LPV/website events.','messaging_conversations',true),
('anti_hallucination_no_purchase_for_awareness_video','anti_hallucination','awareness,video',array['purchases','purchase_value']::text[],'campaign_type in [awareness, video] and purchases/value missing','حملات الوعي والفيديو لا يتم الحكم عليها بالشراء أو ROAS بدون أحداث شراء وقيمة.','ركز على reach/frequency/CPM/video hold/fatigue، واذكر نقص بيانات الشراء فقط عند الحاجة.','frequency',true),
('fatigue_frequency_ctr_cpa','relationships_synthesis','all',array['frequency','ctr_link','cpa']::text[],'frequency up AND ctr_link down AND cpa up','النمط الأقرب هو إجهاد محتوى أو تشبع جمهور، وليس مجرد مشكلة ميزانية.','لا تزود الميزانية قبل اختبار كرياتيفات جديدة أو تقسيم الجمهور. راقب CTR وCPA.','ctr_link',true),
('landing_leak_outbound_lpv','relationships_synthesis','sales,traffic',array['outbound_ctr','lpv_rate']::text[],'outbound_ctr acceptable/high AND lpv_rate low','النقرات الخارجة لا تتحول إلى وصول فعلي؛ المشكلة بعد الضغط.','افحص سرعة الصفحة، الرابط، redirect، التتبع، والاختلاف حسب الجهاز.','lpv_rate',true),
('curiosity_without_intent','relationships_synthesis','sales,leads,messages',array['ctr_link','signal_quality']::text[],'ctr_link high AND signal_quality low','الإعلان يجذب الفضول لكن لا يجلب نية كافية أو هناك عدم تطابق بين الوعد وما بعد الضغط.','غيّر الزاوية والـ CTA والوعد الإعلاني، واختبر نسخة أكثر تأهيلًا للجمهور.','signal_quality',true),
('auction_pressure_cpm_ctr','relationships_synthesis','all',array['cpm','ctr_link']::text[],'cpm up AND ctr_link down','ضغط مزاد أو ضعف جودة الإعلان؛ التكلفة ترتفع والتفاعل يضعف.','اختبر كرياتيف/جمهور بديل، وافحص placement/device لو النمط مستمر.','cpm',true),
('budget_waste_spend_results','budget','all',array['spend','results','cpa']::text[],'spend up AND results flat/down OR cpa up','الإنفاق الإضافي لا يولد نتائج كافية؛ احتمال هدر أو توسع غير صحي.','أعد توزيع الميزانية نحو العناصر ذات result_share أعلى من spend_share، ولا توسع الخاسر.','cpa',true),
('hidden_winner_share_gap','budget','all',array['spend_share','result_share']::text[],'result_share > spend_share with sufficient samples','عنصر رابح مخفي يحصل على نتائج أعلى من حصته من الإنفاق.','زود الميزانية تدريجيًا مع مراقبة CPA/ROAS/frequency.','result_share',true),
('creative_hook_dropoff','creative_content','awareness,video,sales,leads,messages',array['video_3s','video_25','video_50']::text[],'hook/3s acceptable AND hold_25/50 low','البداية تجذب الانتباه لكن جسم المحتوى لا يحتفظ بالمشاهد.','اختصر المقدمة، قدّم البرهان/العرض أسرع، واختبر ترتيب الرسالة.','video_25',true),
('creative_fragile_winner','creative_content','all',array['results','spend','frequency']::text[],'good performance with small sample or short period','الأداء جيد لكنه غير مؤكد بسبب عينة صغيرة أو فترة قصيرة.','لا توسع بعنف؛ ارفع الميزانية تدريجيًا وانتظر عينة كافية.','data_sufficiency_score',true),
('tracking_signal_weak','tracking','sales,leads,traffic',array['clicks','actions']::text[],'clicks/outbound exist AND meaningful events very low/unstable','هناك ضعف إشارة: إما تتبع ناقص أو جودة نية ضعيفة بعد النقر.','افحص Pixel/CAPI/event matching وترتيب الأحداث قبل الحكم النهائي على الإعلان.','signal_quality',true),
('fetch_breakdown_for_saturation','fetch_strategy','all',array['frequency','reach','ctr_link']::text[],'suspected saturation/fatigue','التشخيص يحتاج تفصيل جمهور أو مواضع لفصل إجهاد المحتوى عن تشبع الجمهور.','اسحب breakdowns: age, gender, placement, country عند الحاجة فقط.','frequency',true),
('fetch_breakdown_for_landing_leak','fetch_strategy','sales,traffic',array['outbound_clicks','landing_page_views']::text[],'post-click leak suspected','التسريب بعد الضغط قد يكون مرتبطًا بجهاز أو placement معين.','اسحب breakdown: device وplacement قبل توصية تقنية نهائية.','lpv_rate',true),
('report_must_include_evidence_confidence_next_metric','reporting','all',array[]::text[],'always','كل تقرير يجب أن يوضح الدليل والثقة والقرار والرقم التالي للمراقبة.','استخدم skipped_sections للأقسام غير المدعومة بدل عرضها.','varies',true)
on conflict (rule_key) do update set
  layer=excluded.layer,
  campaign_type=excluded.campaign_type,
  required_metrics=excluded.required_metrics,
  condition_logic=excluded.condition_logic,
  meaning_ar=excluded.meaning_ar,
  recommended_action_ar=excluded.recommended_action_ar,
  next_metric=excluded.next_metric,
  enabled=excluded.enabled,
  updated_at=now();

select count(*) as seeded_rules from public.knowledge_rules where rule_key in ('anti_hallucination_no_website_funnel_for_messages','anti_hallucination_no_purchase_for_awareness_video','fatigue_frequency_ctr_cpa','landing_leak_outbound_lpv','curiosity_without_intent','auction_pressure_cpm_ctr','budget_waste_spend_results','hidden_winner_share_gap','creative_hook_dropoff','creative_fragile_winner','tracking_signal_weak','fetch_breakdown_for_saturation','fetch_breakdown_for_landing_leak','report_must_include_evidence_confidence_next_metric');
