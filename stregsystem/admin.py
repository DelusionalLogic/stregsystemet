from django.contrib import admin
from django.utils import timezone
from stregsystem.models import Sale, Member, Payment, News, Product, Room
import fpformat

class SaleAdmin(admin.ModelAdmin):
    list_filter = ('room', 'timestamp')
    list_display = ('get_username', 'get_product_name', 'get_room_name', 'timestamp', 'get_price_display')

    def get_username(self, obj):
        return obj.member.username
    get_username.short_description = "Username"
    get_username.admin_order_field = "member__username"

    def get_product_name(self, obj):
        return obj.product.name
    get_product_name.short_description = "Product"
    get_product_name.admin_order_field = "product__name"

    def get_room_name(self, obj):
        return obj.room.name
    get_room_name.short_description = "Room"
    get_room_name.admin_order_field = "room__name"

    def get_price_display(self, obj):
        if obj.price is None:
            obj.price = 0
        return fpformat.fix(obj.price/100.0,2)   + " kr."
    get_price_display.short_description = "Price"
    get_price_display.admin_order_field = "price"

    search_fields = ['^member__username', '=product__id', 'product__name']
    valid_lookups = ('member')

def toggle_active_selected_products(modeladmin, request, queryset):
    "toggles active on products, also removes deactivation date."
    # This is horrible since it does not use update, but update will
    # not do not F('active') so we are doing this. I am sorry.
    for obj in queryset:
        obj.deactivate_date = None
        obj.active = not obj.active
        obj.save()

class ProductAdmin(admin.ModelAdmin):
    search_fields = ('name', 'price', 'id')
    list_filter = ('deactivate_date', 'price')
    list_display = ('activated', 'id', 'name', 'get_price_display')
    actions = [toggle_active_selected_products]

    def get_price_display(self, obj):
        if obj.price is None:
            obj.price = 0
        return fpformat.fix(obj.price/100.0,2)   + " kr."
    get_price_display.short_description = "Price"
    get_price_display.admin_order_field = "price"

    def activated(self, obj):
        if obj.active and (obj.deactivate_date == None or obj.deactivate_date > timezone.now()):
            return '<img src="/static/admin/img/icon-yes.svg" alt="1" />'
        else:
            return '<img src="/static/admin/img/icon-no.svg" alt="0" />'
    activated.allow_tags = True

class MemberAdmin(admin.ModelAdmin):
    list_filter = ('want_spam', )
    search_fields = ('username', 'firstname', 'lastname', 'email')
    list_display = ('username', 'firstname', 'lastname', 'balance', 'email', 'notes')

class PaymentAdmin(admin.ModelAdmin):
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "member":
            kwargs["queryset"] = Member.objects.filter(active=True).order_by('username')
            return db_field.formfield(**kwargs)
        return super(SmarterModelAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

    list_display = ('get_username', 'timestamp', 'get_amount_display')
    valid_lookups = ('member')
    search_fields = ['member__username']

    def get_username(self, obj):
        return obj.member.username
    get_username.short_description = "Username"
    get_username.admin_order_field = "member__username"

    def get_amount_display(self, obj):
        if obj.amount is None:
            obj.amount = 0
        return fpformat.fix(obj.amount/100.0,2)   + " kr."
    get_amount_display.short_description = "Amount"
    get_amount_display.admin_order_field = "amount"


admin.site.register(Sale, SaleAdmin)
admin.site.register(Member, MemberAdmin)
admin.site.register(Payment, PaymentAdmin)
admin.site.register(News)
admin.site.register(Product, ProductAdmin)
admin.site.register(Room)
