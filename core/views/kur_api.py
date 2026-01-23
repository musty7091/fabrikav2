from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required

from core.services.exchange_rates import get_try_per_currency


@require_GET
@login_required
def kur_getir(request):
    pb = (request.GET.get("pb") or "").upper().strip()
    d = (request.GET.get("date") or "").strip()  # YYYY-MM-DD (opsiyonel)

    res = get_try_per_currency(pb, for_date=d if d else None)

    if not res.ok or res.rate is None:
        return JsonResponse(
            {"ok": False, "pb": pb, "date": d or None, "message": res.message or "Kur alınamadı"},
            status=200
        )

    return JsonResponse({
        "ok": True,
        "pb": pb,
        "date": d or None,
        "rate": str(res.rate),
        "source": res.source,
    })
