# 野草公开留言壁：人人可见的墙（与联系我们私信分轨，禁止共用表）

import uuid

from django.db import models

from .time_helpers import now_local_wall


class PublicWallPost(models.Model):
    """墙上的一楼。楼号先来后到，不因排序重排。藏/删只改状态，库内留条。"""

    STATUS_VISIBLE = 'visible'
    STATUS_HIDDEN = 'hidden'
    STATUS_DELETED = 'deleted'
    STATUS_CHOICES = [
        (STATUS_VISIBLE, '正常'),
        (STATUS_HIDDEN, '已隐藏'),
        (STATUS_DELETED, '已删除'),
    ]

    post_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, verbose_name='留言ID',
    )
    floor_no = models.PositiveIntegerField(
        unique=True, db_index=True, verbose_name='楼号',
        help_text='先发的是 1 楼；不因最新在上而重排',
    )
    body = models.CharField(max_length=500, verbose_name='正文')
    display_name = models.CharField(max_length=80, verbose_name='对外显示名')
    nickname_input = models.CharField(
        max_length=80, blank=True, default='', verbose_name='当时填写的昵称',
    )
    is_anonymous = models.BooleanField(default=False, verbose_name='当时勾选匿名')
    actor_key = models.CharField(
        max_length=80, blank=True, default='', db_index=True, verbose_name='发言身份键',
        help_text='已登录用账号；未登录用浏览器访客编号，用于按人限流',
    )
    author_user_id = models.CharField(
        max_length=64, blank=True, default='', verbose_name='登录账号快照',
    )
    author_ip = models.GenericIPAddressField(blank=True, null=True, verbose_name='发言IP')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_VISIBLE,
        db_index=True, verbose_name='状态',
    )
    created_at = models.DateTimeField(
        default=now_local_wall, db_index=True, verbose_name='发言时间',
    )

    class Meta:
        db_table = 'public_wall_post'
        ordering = ['-floor_no']
        verbose_name = '公开留言壁楼'
        verbose_name_plural = '公开留言壁楼'

    def __str__(self):
        return f'{self.floor_no}楼'

    def status_public_notice(self) -> str:
        """大厅藏/删占位文案；正常楼为空。只读状态，不另存一份。"""
        if self.status == self.STATUS_HIDDEN:
            return '本条留言已被隐藏'
        if self.status == self.STATUS_DELETED:
            return '本条留言已被删除'
        return ''


class PublicWallReply(models.Model):
    """管理者对某一楼的平铺回；不占新楼号，不计入访客发帖限额。"""

    KIND_NOTE = 'note'
    KIND_REPLY = 'reply'
    KIND_CHOICES = [
        (KIND_NOTE, '说明'),
        (KIND_REPLY, '回复'),
    ]
    DEFAULT_SIGNER = '管理员'
    MAX_SIGNER = 40

    reply_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, verbose_name='回复ID',
    )
    post = models.ForeignKey(
        PublicWallPost, on_delete=models.CASCADE, related_name='replies',
        verbose_name='所属楼',
    )
    body = models.CharField(max_length=500, verbose_name='正文')
    signer_name = models.CharField(
        max_length=40, blank=True, default='', verbose_name='对外署名',
        help_text='手填，如管理员、外卖大叔；空则按管理员显示',
    )
    suffix_kind = models.CharField(
        max_length=16, blank=True, default='', choices=KIND_CHOICES,
        verbose_name='后缀种类',
        help_text='note=说明（藏/删）；reply=回复（正常回）；旧条为空则按说明',
    )
    created_at = models.DateTimeField(
        default=now_local_wall, db_index=True, verbose_name='写下时间',
    )

    def public_heading(self) -> str:
        """大厅/后台给人看的「署名+说明/回复」；旧条空字段按管理员说明。"""
        signer = (self.signer_name or '').strip() or self.DEFAULT_SIGNER
        if (self.suffix_kind or '').strip() == self.KIND_REPLY:
            return f'{signer}回复'
        return f'{signer}说明'

    class Meta:
        db_table = 'public_wall_reply'
        ordering = ['created_at']
        verbose_name = '公开留言壁管理者说明'
        verbose_name_plural = '公开留言壁管理者说明'
