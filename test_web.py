#!/bin/env python
#coding=utf-8
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/vendor/')

import tornado
import tornado.options
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.escape
import tornado.httpclient
import tornado.gen
import tornado.locale
import tornado.auth
import tornado.template
from tornado.escape import json_encode, json_decode

import time
import string
import urllib
import random
import hashlib
import uuid
import xmltodict
import base64

import xlrd

from controller import base
from controller import apps_info

from controller.base import WebRequest
from controller.base import WebSocket
from controller.apps_info import hotpoor_apps

import nomagic
import nomagic.order
import nomagic.auth
import nomagic.setting
from nomagic.setting import conn

import requests
import qiniu
from qiniu import put_file, etag, urlsafe_base64_encode

qiniu_hotpoor_access_key = 'nyAmycfeo4-RF6drKPf62_KU1RUvj8lFsrmOqJ9K'
qiniu_hotpoor_secret_key = 'NBaVPYokRuMvmthKWjabxFGCxQ0yx5h-ZSQwsJrk'

yunpian = {
    "sms_send":"https://sms.yunpian.com:443/v1/sms/send.json",
    "port":"443",
    "version":"v1",
    "apikey":"723fdf1f8360cb854421707fcc739d8e"
}

sms_apps = ["hotpoor"]
weixin_apps = ["hotpoor"]
weixin_apps_dev_info = {
    "hotpoor":{
        "ShopNumber":"1285500601",
        "ShopNumberKey":"hotpoorinchina88xlwlovezhanglu36",
        "Id":"gh_fe913d164ebf",
        "AppId":"wx2ca08b0c9fad1e69",
        "AppSecret":"c04fd723f2f80ca97c92fd8cbb072d7f",
    }
}

weixin_JS_SDK_access_tokens = {}
weixin_JS_SDK_jsapi_tickets = {}
weixin_JS_SDK_access_token_timers = {}


class CheckExcelAPIHandler(WebRequest):
    def get(self):
        self.finish({u"info":u"It's necessary to check excel file."})
    def post(self):
        # upload_path = os.path.join(os.path.dirname(__file__),'files')
        file_metas = self.request.files['file']
        print file_metas
        data = xlrd.open_workbook(file_contents=file_metas[0].get('body'),formatting_info=1)
        print data.sheet_names()
        print u"Sheet数量:%s" % len(data.sheets())
        for table in data.sheets():
            nrows = table.nrows
            ncols = table.ncols
            print u"%s行%s列" % (nrows,ncols)
            for i in range(nrows):
                print table.row_values(i)
                for j in range(ncols):
                    print table.cell_value(i,j)
                    print table.cell(i,j)
                    # print table.cell_xf_index(i,j)
                    print "========"



        data_type = self.get_argument("type")
        print "data_type: %s" % data_type


        self.finish({u"type":u"excel",u"data":{}})




settings = {
    "static_path":os.path.join(os.path.dirname(__file__),"static"),
    "cookie_secret": "hotpoorinchina"
    }

application = tornado.web.Application([
    (r"/api/file/check_excel",CheckExcelAPIHandler),

    (r"/api/user/update_weixin_data/",UpdateWeixinDataUserAPIHandler),

    #==========================
    #微信相关服务器配置、API和支付等
    #==========================
    #支付授权目录
    (r"/wechat/webpay/",WechatWebpayHandler),
    (r"/wechat/webpay/callback/(.*)",WechatWebpayCallbackHandler),
    #测试授权目录
    (r"/wechat/webpaytest/",WechatWebpayTestHandler),
    (r"/wechat/webpaytest/callback/(.*)",WechatWebpayTestCallbackHandler),
    #支付回调URL 微信扫码支付
    (r"/wechat/qrcodepaybackurl/",WechatQrcodepaybackurlHandler),

    (r"/wechat/developer/api/hotpoor",WechatDeveloperAPIHotpoorHandler),

    #==========================
    #/map/(.*)产品系列 独立
    #==========================
    (r"/home/map/(.*)",                     HomeMapBaseHandler),
    (r"/home/map",                          HomeMapHandler),

    #==========================
    #/tools/(.*)产品系列 独立
    #==========================
    (r"/home/tools/webgl_panorama_dualfisheye", HomeToolsWebglPanoramaDualfisheyeHandler),
    (r"/home/tools/webgl_video_panorama_equirectangular", HomeToolsWebglVideoPanoramaEquirectangularHandler),

    #==========================
    #/home/*产品系列 所有其他产品在这个上面得
    #==========================
    (r"/home/(.*)", HomeHandler),

    #==========================
    #/api/*产品系列
    #==========================
    (r"/api/weixin/hotpoor/download",   WeixinDownloadHotpoorAPIHandler),
    (r"/api/user/check",                UserCheckAPIHandler),
    (r"/api/user/info",                 UserInfoAPIHandler),
    # (r"/api/user/add",              UserAddAPIHandler),
    # (r"/api/user/set_password",     UserSetPasswordAPIHandler),
    # (r"/api/user/set_name",         UserSetNameAPIHandler),
    (r"/api/user/set_headimgurl",       UserSetHeadImgUrlAPIHandler),

    (r"/api/sms/yunpian/send", SMSYunpianSendAPIHandler),

    #==========================
    #退出应用
    #==========================
    (r"/api/user/logout",   UserLogoutAPIHandler),
    (r"/logout",            LogoutAPIHandler),

    #==========================
    #其他
    #==========================
    (r"/ws",WebSocketHandler),
    (r"/static/(.*)", tornado.web.StaticFileHandler, dict(path=settings['static_path'])),
    (r"/(.*)", MainHandler),
    ], **settings)

if __name__ == "__main__":
    tornado.options.define("port", default=8036, help="Run server on a specific port", type=int)
    tornado.options.parse_command_line()
    application.listen(tornado.options.options.port)
    tornado.ioloop.IOLoop.instance().start()
    # application.listen(8036)
    # tornado.ioloop.IOLoop.current().start()
