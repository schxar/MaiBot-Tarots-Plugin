# MaiBot-Tarot-Action-plugins
这是给MaiM-with-u项目开发的一个抽塔罗牌插件

现已适配最新的dev0.8.0最新插件系统，如果出现问题就等待更新吧，dev分支将保持与最新dev兼容，不考虑回退。

参考了https://github.com/FloatTech/ZeroBot-Plugin
的塔罗牌插件进行开发

卡牌图片来自于https://github.com/FloatTech/zbpdata

在此鸣谢[ZeroBot插件开发组](https://github.com/FloatTech)
提供的抽牌功能思路，塔罗牌数据和卡牌图片仓库支持

在此鸣谢MaiM-with-u开发组人员的指导和帮助

完整的文件结构都包含在tarots_plugin这个大文件夹内，直接将这个大文件夹放入plugins中就能用。

使用时需指定抽牌方式和抽牌范围，目前已默认支持的有

牌阵："单张", "圣三角", "时间之流","四要素","五牌阵","吉普赛十字","马蹄","六芒星"

如果没有明确指定，默认抽"单张"。

范围："全部", "大阿卡纳", "小阿卡纳"

如果没有明确指定，默认抽"全部"。

注意，本插件的图片来源是Github的仓库，因此需要你的麦麦部署设备的网络环境能够流畅地访问Github。

不过不用担心，这个插件有缓存机制，发过的图片都会被缓存在插件的tarots_cache文件夹中，如果你缓存了全部的卡牌图片，那么你就不用担心连不上Github怎么办了。

新增了一键缓存指令/tarots cache，其内部的配置文件config.toml内包含限制能够使用指令的人的选项，请自行填写QQ号。

目前main分支只支持070正式版，dev分支目前支持0.8.0版本。
