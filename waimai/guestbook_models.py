# 服务器主页留言板（正式功能 · 表名沿用 owner_guestbook_* 以保留历史数据）

import uuid

from django.db import models


class GuestbookSettings(models.Model):
    """联系我们积木：对外名称与邮箱由管理者填写，不写死在代码里。"""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False, verbose_name='固定编号',
    )
    public_display_name = models.CharField(
        max_length=80, blank=True, default='', verbose_name='对外名称',
    )
    public_contact_email = models.CharField(
        max_length=254, blank=True, default='', verbose_name='联系邮箱',
    )
    block_intro = models.TextField(
        blank=True, default='', verbose_name='联系我们说明',
        help_text='显示在服务器主页「联系我们」积木中',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'owner_guestbook_settings'
        verbose_name = '联系我们设置'
        verbose_name_plural = '联系我们设置'

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        return super().save(*args, **kwargs)


class GuestbookThread(models.Model):
    """一条留言主题；体验日清不删除。"""

    thread_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, verbose_name='主题ID',
    )
    public_code = models.CharField(
        max_length=20, unique=True, db_index=True, blank=True, default='',
        verbose_name='对外留言编号',
        help_text='格式 YC-MMDD-xxxxxxxx，当天唯一',
    )
    guest_display_name = models.CharField(max_length=80, blank=True, default='', verbose_name='访客称呼')
    guest_email = models.CharField(max_length=254, blank=True, default='', verbose_name='访客邮箱')
    guest_user_id = models.CharField(max_length=64, blank=True, default='', verbose_name='登录账号快照')
    guest_actor_key = models.CharField(
        max_length=80, blank=True, default='', db_index=True, verbose_name='留言身份键',
        help_text='已登录用账号；未登录用浏览器访客编号，用于按人限流',
    )
    guest_password_hash = models.CharField(
        max_length=128, blank=True, default='', verbose_name='查看密码（加密）',
    )
    author_ip = models.GenericIPAddressField(blank=True, null=True, verbose_name='首次留言IP')
    receipt_email_failed = models.BooleanField(
        default=False, verbose_name='收条邮件当场发送失败',
    )
    receipt_email_rate_limited = models.BooleanField(
        default=False, verbose_name='收条邮件因防刷上限未发',
    )
    email_delivery_suspect = models.BooleanField(
        default=False, verbose_name='邮箱可能无法收信',
        help_text='管理者标记或事后发现退信时使用',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='创建时间')
    last_activity_at = models.DateTimeField(auto_now=True, db_index=True, verbose_name='最后活动时间')
    owner_read_at = models.DateTimeField(blank=True, null=True, verbose_name='管理者已读时间')

    class Meta:
        db_table = 'owner_guestbook_thread'
        ordering = ['-last_activity_at']
        verbose_name = '留言主题'
        verbose_name_plural = '留言主题'

    @property
    def has_view_password(self) -> bool:
        return bool((self.guest_password_hash or '').strip())

    @property
    def owner_unread(self) -> bool:
        latest = self.messages.order_by('-created_at').first()
        if not latest or latest.author_side != 'guest':
            return False
        if self.owner_read_at is None:
            return True
        return latest.created_at > self.owner_read_at


class GuestbookMessage(models.Model):
    """留言或回复"""

    SIDE_CHOICES = [
        ('guest', '访客'),
        ('owner', '管理者'),
    ]

    message_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, verbose_name='消息ID',
    )
    thread = models.ForeignKey(
        GuestbookThread, on_delete=models.CASCADE, related_name='messages', verbose_name='所属主题',
    )
    author_side = models.CharField(max_length=8, choices=SIDE_CHOICES, db_index=True, verbose_name='发言方')
    author_label = models.CharField(max_length=80, blank=True, default='', verbose_name='显示名快照')
    body = models.CharField(max_length=1000, verbose_name='内容')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发送时间')
    guest_notified = models.BooleanField(default=False, verbose_name='已邮件通知访客')

    class Meta:
        db_table = 'owner_guestbook_message'
        ordering = ['created_at']
        verbose_name = '留言消息'
        verbose_name_plural = '留言消息'
